"""管线瀑布：把多步计税编排成数据文件（data/pipelines/*.yaml）。

YAML 形态::

    id: engineering_to_owner
    title: 工程款 -> 老板到手（单期快照）
    steps:
      - as: vat_taxable            # 步骤名即变量名
        desc: 价税分离后的不含税收入
        op: expr                   # 算术表达式（安全求值）
        expr: contract_gross / (1 + levy_rate)
      - as: vat_payable
        desc: 增值税
        op: rule                   # 引用规则库执行原语
        rule: cn/vat/small_scale_levy
        args: {base: contract_gross - vat_taxable}
      ...

变量解析顺序：用户输入 > 前序步骤结果。expr 与 rule.args 的值若为
字符串一律按安全算式求值（ast 白名单：变量名/数字/+ - * / ()），
禁止任何函数调用与属性访问，杜绝注入。
每步自动携带规则版本与文号进入审计链。
"""
import ast
import operator as op

from .calculator import Calculator, fmt
from .loader import load_all, resolve  # noqa: F401 (resolve供外部复用)
from .primitives import F, TaxEngineError


class PipelineError(TaxEngineError):
    pass


# ---- 安全算术求值 -------------------------------------------------
_ALLOWED_BINOPS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
    ast.Div: op.truediv, ast.Pow: None,   # Pow 不放开，防大数炸弹
}
_ALLOWED_UNARY = {ast.USub: op.neg, ast.UAdd: op.pos}
_ALLOWED_CMP = {
    ast.LtE: op.le, ast.Lt: op.lt, ast.GtE: op.ge, ast.Gt: op.gt,
    ast.Eq: op.eq, ast.NotEq: op.ne,
}


def safe_eval(expr, variables):
    """只允许 变量名/数字/(+-*/) 与比较运算的白名单求值器。
    比较表达式返回 Fraction(1)/Fraction(0)，供 assert 步骤使用。"""
    def _ev(node):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(
                node.value, (int, float)):
            return F(node.value)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise PipelineError("未知变量 %r（可用：%s）"
                                    % (node.id, ", ".join(sorted(variables))))
            return F(variables[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            return _ALLOWED_BINOPS[type(node.op)](_ev(node.left),
                                                  _ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(node.op)](_ev(node.operand))
        if isinstance(node, ast.Compare) and len(node.ops) == 1 \
                and type(node.ops[0]) in _ALLOWED_CMP:
            ok = _ALLOWED_CMP[type(node.ops[0])](_ev(node.left),
                                                 _ev(node.comparators[0]))
            return F(1 if ok else 0)
        raise PipelineError("表达式含不允许的语法: %s" % ast.dump(node))

    try:
        tree = ast.parse(str(expr), mode="eval")
    except SyntaxError as e:
        raise PipelineError("表达式语法错误 %r: %s" % (expr, e))
    return _ev(tree)


# ------------------------------------------------------------------
class PipelineResult(dict):
    """dict 形态：{变量: Fraction}，附 .steps 审计链与 .render()。"""

    def __init__(self):
        super().__init__()
        self.steps = []
        self.title = ""

    def render(self):
        out = ["# %s -- 计算瀑布" % self.title, ""]
        out.append("| # | 项目 | 数值 |")
        out.append("|---|---|---|")
        for i, s in enumerate(self.steps, 1):
            sym = "=" if s.get("is_result") else ""
            out.append("| %d | %s%s | %s |" % (
                i, s.get("desc") or s["as"],
                " **<-- 到手**" if s.get("is_result") else "",
                fmt(s["value"])))
        out.append("")
        out.append("## 依据链")
        out.append("")
        out.append("| # | 步骤 | 适用版本 | 文号 | 核验 |")
        out.append("|---|---|---|---|---|")
        for i, s in enumerate(self.steps, 1):
            src = s.get("source") or {}
            out.append("| %d | %s | %s | %s | %s |" % (
                i, s.get("desc") or s["as"], s.get("effective", "-"),
                src.get("doc_no", "-") if src else "-",
                s.get("verified_at", "-")))
        out.append("")
        out.append("> 输出仅为工具计算结果，不构成税务建议；"
                   "金额为两位小数展示值，引擎内部全程精确分数。")
        return "\n".join(out)


def run_pipeline(pipeline_def, tx_date, inputs, calculator=None):
    """pipeline_def: 已加载的 dict；inputs: {str: 可转Fraction的值}。"""
    res = PipelineResult()
    res.title = pipeline_def.get("title", pipeline_def.get("id"))
    ctx = dict(inputs)
    return _run(pipeline_def, tx_date, ctx, res, calculator)


def _run(pipeline_def, tx_date, ctx, res, calculator):
    from .calculator import Calculator as _C  # 局部导入规避循环

    calc = calculator if calculator is not None else _C()

    for st in pipeline_def.get("steps", []):
        name = st.get("as")
        if not name:
            raise PipelineError("步骤缺少 as 字段: %r" % st)
        if st.get("op") == "rule":
            rule_id = st["rule"]
            args = {
                k: (safe_eval(v, ctx) if isinstance(v, str) else v)
                for k, v in (st.get("args") or {}).items()
            }
            val, audit = calc.apply(rule_id, tx_date, args)
            res.steps.append({
                "as": name, "desc": st.get("desc", rule_id),
                "value": val, "effective": audit["effective"],
                "effective_end": audit.get("effective_end"),
                "source": audit["source"],
                "verified_at": audit.get("verified_at"),
                "is_result": bool(st.get("result")),
            })
        elif st.get("op") == "expr":
            val = safe_eval(st.get("expr"), ctx)
            entry = {"as": name, "desc": st.get("desc", name),
                     "value": val}
            if st.get("source"):
                entry["source"] = st["source"]
            if st.get("effective"):
                entry["effective"] = st["effective"]
            res.steps.append(entry)
        elif st.get("op") == "param_or_input":
            # 输入了就用输入值；否则取 default 注入上下文
            key = st.get("key", name)
            if key in ctx:
                val = F(ctx[key])
            else:
                val = F(st.get("default", 0))
            res.steps.append({"as": name,
                              "desc": st.get("desc", name), "value": val})
        elif st.get("op") == "assert":
            # 条件不成立即整体拒答（演示引擎拒绝越界假设）
            ok = safe_eval(st["expr"], ctx)
            if ok != 1:
                raise TaxEngineError(
                    "[拒答] %s" % st.get("message",
                                         "断言失败: %s" % st.get("expr")))
            continue                      # 断言步骤本身不进入瀑布展示
        elif st.get("op") == "param":
            # 运行期从规则库解析参数（如当前征收率），本身不产生税额
            from .loader import resolve as _resolve
            tbl = _resolve(calc.registry, st["rule"], tx_date)
            key = st.get("param", "rate")
            val = F(tbl["params"][key])
            res.steps.append({
                "as": name, "desc": st.get("desc", name),
                "value": val,
                "effective": "%s 至 %s" % (tbl["_start"],
                                           tbl["_end"] or "至今"),
                "effective_end":
                    tbl["_end"].isoformat() if tbl["_end"] else None,
                "source": tbl.get("source", {}),
                "verified_at": tbl.get("last_verified"),
            })
        else:
            raise PipelineError("未知步骤 op: %r" % st.get("op"))
        # 结果同时写回 求值上下文 与 结果字典（供枚举器读取 owner_net 等）
        ctx[name] = val
        res[name] = val
    return res
