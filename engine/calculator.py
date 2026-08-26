"""Calculator -- 统一入口：解析规则版本 -> 执行原语 -> 记录审计链。"""
import datetime as _dt
from fractions import Fraction

from .loader import load_all, resolve
from .primitives import DISPATCH, F, TaxEngineError


def _default_rules_root():
    import os

    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
    )


class Calculator:
    """用法::

        c = Calculator()
        tax, step = c.apply("cn/iit/comprehensive_annual",
                            "2026-03-01", {"amount": 300000})
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
            "effective": "%s 至 %s"
            % (tbl["_start"], tbl["_end"] or "至今"),
            "verified_at": tbl.get("last_verified"),
            "verified_by": tbl.get("verified_by"),
            "source": tbl.get("source", {}),
            "inputs": {k: str(v) for k, v in clean_args.items()},
            "result": out["value"],
            "detail": out.get("audit", {}),
        }
        self.trace.append(step)
        return out["value"], step

    # ---- 报告渲染 -------------------------------------------------
    def markdown_report(self, title="计税审计链"):
        lines = [
            "# %s" % title,
            "",
            "| # | 项目 | 结果(元) | 适用版本 | 依据 |",
            "|---|---|---|---|---|",
        ]
        for i, s in enumerate(self.trace, 1):
            src = s["source"]
            basis = "%s %s" % (
                src.get("title", ""),
                "(%s)" % src.get("doc_no", "") if src.get("doc_no") else "",
            )
            lines.append(
                "| %d | %s | %.2f | %s | %s |"
                % (
                    i,
                    s.get("description") or s["rule"],
                    float(s["result"]),
                    s["effective"],
                    basis.strip(),
                )
            )
        return "\n".join(lines) + "\n"

    def result(self, key):
        """取某一步的结果（step 名即 rule id 最后一段 + 序号兜底）。"""
        for s in self.trace:
            if s["rule"].rsplit("/", 1)[-1] == key:
                return s["result"]
        raise TaxEngineError("trace 中不存在: %s" % key)


def rule_flat_rate(registry, rule_id, tx_date):
    """供 price_split 使用：取 flat 规则在指定日期的 rate 参数。"""
    tbl = resolve(registry, rule_id, tx_date)
    if tbl["primitive"] != "flat":
        raise TaxEngineError("%s 不是 flat 规则" % rule_id)
    return F(tbl["params"]["rate"])
