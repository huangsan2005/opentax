"""Calculator -- 统一入口：解析规则版本 -> 执行原语 -> 记录审计链。

每一步审计包含：所用规则版本与生效区间、来源文号、输入参数、结果。
LLM 编排层把这份链路渲染给用户，用户可逐项核对文号。
"""
import datetime as _dt
import os
from fractions import Fraction

from .loader import load_all, resolve
from .primitives import DISPATCH, F, TaxEngineError


def _default_rules_root():
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    return os.path.join(root, "data", "rules")


class Calculator:
    """用法::

        c = Calculator()
        tax, step = c.apply("cn/vat/small_scale_levy",
                            "2026-03-01", {"base": 100000})
        print(c.markdown_report())
    """

    def __init__(self, rules_root=None):
        self.rules_root = rules_root or _default_rules_root()
        self.registry = load_all(self.rules_root)
        self.trace = []

    def apply(self, rule_id, tx_date, args):
        tbl = resolve(self.registry, rule_id, tx_date)
        d = _dt.date.fromisoformat(str(tx_date))
        clean_args = {k: F(v) for k, v in args.items()}
        prim = DISPATCH[tbl["primitive"]]
        out = prim(clean_args, tbl.get("params") or {})
        step = {
            "rule": rule_id,
            "primitive": tbl["primitive"],
            "description": tbl.get("description", ""),
            "effective": "%s 至 %s" % (tbl["_start"], tbl["_end"] or "至今"),
            "effective_end": tbl["_end"].isoformat() if tbl["_end"] else None,
            "verified_at": tbl.get("last_verified"),
            "verified_by": tbl.get("verified_by"),
            "source": tbl.get("source", {}),
            "notes": tbl.get("notes") or [],
            "inputs": {k: str(v) for k, v in clean_args.items()},
            "result": out["value"],
            "detail": out.get("audit", {}),
            "tx_date": str(d),
        }
        self.trace.append(step)
        return out["value"], step

    def markdown_report(self, title="计税审计链"):
        lines = [
            "# %s" % title,
            "",
            "| # | 项目 | 结果(元) | 适用版本 | 依据 |",
            "|---|---|---|---|---|",
        ]
        for i, s in enumerate(self.trace, 1):
            src = s.get("source") or {}
            basis = ("%s %s" % (src.get("title", ""),
                                ("(%s)" % src["doc_no"])
                                if src.get("doc_no") else "")).strip()
            lines.append("| %d | %s | %.2f | %s | %s |" % (
                i, s.get("description") or s["rule"],
                float(s["result"]), s["effective"], basis))
        det = self.trace[-1]["detail"] if self.trace else {}
        if det:
            lines.append("")
            lines.append("计算明细：%s" % det)
        src = (self.trace[-1].get("source") or {}) if self.trace else {}
        if src.get("doc_no"):
            lines.append("")
            lines.append("依据：%s（核验于 %s）"
                         % (src.get("doc_no"),
                            self.trace[-1].get("verified_at")))
        lines.append("")
        lines.append("> 输出仅为工具计算结果，不构成税务建议。")
        return "\n".join(lines)


def fmt(x):
    """Fraction -> 两位小数字符串（仅展示层舍入）。"""
    f = Fraction(x)
    q = Fraction(round(f * 100), 100)
    return "{:,.2f}".format(float(q))


def rule_flat_rate(registry, rule_id, tx_date):
    """供管线取某 flat 规则在指定日期的 rate 参数。"""
    tbl = resolve(registry, rule_id, tx_date)
    if tbl["primitive"] != "flat":
        raise TaxEngineError("%s 不是 flat 规则" % rule_id)
    return F(tbl["params"]["rate"])
