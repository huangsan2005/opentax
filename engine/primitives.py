"""六大确定性原语。引擎不知道任何具体税种名称。

每个函数返回包含 value(Fraction) 与 audit 明细的字典，
由 calculator 层包装成统一审计步骤。
"""
from fractions import Fraction


class TaxEngineError(Exception):
    """引擎基础异常。"""


class OutOfScope(TaxEngineError):
    """交易日期没有命中任何规则版本 --> 拒绝作答，绝不硬算。"""

    def __init__(self, rule_id, tx_date, windows):
        self.rule_id = rule_id
        self.tx_date = tx_date
        self.windows = windows
        ranges = "; ".join(
            "%s 至 %s" % (w[0] or "不限", w[1] or "至今") for w in windows
        )
        super().__init__(
            "[拒答] %s 无覆盖 %s 的版本（已收录区间：%s）。"
            "数据超出内置范围时不做推测。" % (rule_id, tx_date, ranges)
        )


def F(v):
    """int/str/Fraction/Decimal 字符串安全转 Fraction，避免浮点误差。"""
    return Fraction(str(v))


def _clamp_nonneg(x):
    return x if x > 0 else Fraction(0)


# ---------------------------------------------------------------
# 1) flat -- 比例税率（可带固定减免），如增值税征收率、分红股息 20%
# ---------------------------------------------------------------
def flat(args, params):
    """
    args:   base 计税基础; deduct 可选固定减免
    params: rate 必填; clamp_nonneg 缺省 true
    返回: tax = base * rate - deduct
    """
    base = F(args["base"])
    rate = F(params["rate"])
    deduct = F(args.get("deduct", 0))
    tax = base * rate - deduct
    if params.get("clamp_nonneg", True):
        tax = _clamp_nonneg(tax)
    return {
        "value": tax,
        "audit": {
            "formula": "base×rate−deduct",
            "base": base,
            "rate": rate,
            "deduct": deduct,
        },
    }


# ---------------------------------------------------------------
# 2) multiply -- 数据驱动的百分比调整（减半、减按25%计入等）
# ---------------------------------------------------------------
def multiply(args, params):
    val = F(args["value"]) * F(params["factor"])
    return {
        "value": val,
        "audit": {"formula": "value×factor"},
    }


# ---------------------------------------------------------------
# 3) progressive -- 超额累进（个人所得税类）。
#    同时给两条路径：逐档切片累加 与 速算扣除公式，二者必须一致。
# ---------------------------------------------------------------
def progressive(args, params):
    amount = F(args["amount"])
    brackets = params["brackets"]  # loader 已保证有序不重叠
    # 路径A：逐档切片
    sliced = Fraction(0)
    slices = []
    lo = Fraction(0)
    for b in brackets:
        hi = F(b["max_amount"]) if b.get("max_amount") is not None else None
        rate = F(b["rate"])
        upper = amount if hi is None else min(amount, hi)
        if upper > lo:
            seg = (upper - lo) * rate
            sliced += seg
            slices.append(
                {"range": (lo, hi), "portion": upper - lo, "rate": rate,
                 "tax": seg}
            )
        lo = hi if hi is not None else lo
        if hi is not None and amount <= hi:
            break
    # 路径B：速算扣除
    br = _match_bracket(brackets, lambda m: m <= amount, "max_amount")
    quick_total = (
        amount * F(br["rate"]) - F(br.get("quick_deduct", 0))
        if amount > 0 else Fraction(0)
    )
    if sliced != quick_total:
        raise TaxEngineError(
            "内部一致性破坏：切片法 %s != 速算法 %s"
            % (float(sliced), float(quick_total))
        )
    return {
        "value": quick_total,
        "audit": {"matched_bracket": br, "slices": slices,
                  "consistency": "slice==quick ✓"},
    }


def _match_bracket(brackets, predicate, field):
    """返回最后一个满足谓词的括号；字段缺失视为开口档（最高档）。"""
    hit = None
    for b in brackets:
        v = b.get(field)
        if v is None:
            hit = b          # 开口档始终是候选（位于序列末尾）
            continue
        if predicate(F(v)):
            hit = b
        else:
            break
    if hit is None:
        raise TaxEngineError("未匹配到税级区间")
    return hit


# ---------------------------------------------------------------
# 4) super_progressive -- 超率累进（土地增值税类）。
#    增值率 = 增值额 ÷ 扣除项目；档内公式：
#    税 = 增值额×率 − 扣除项目×速算扣除系数（系数作用于扣除项目）。
#    扣除项目为 0 时增值率视同无穷大，落最高档（T20000 表填报口径）。
# ---------------------------------------------------------------
def super_progressive(args, params):
    amount = F(args["amount"])       # 增值额
    base = F(args["base"])           # 扣除项目金额
    brackets = params["brackets"]
    if base == 0:
        ratio = None                 # 无穷大
        br = brackets[-1]
    else:
        ratio = amount / base
        lo_ok = []
        for b in brackets:
            lo_b = F(b["min_ratio"]) if b.get("min_ratio") is not None else None
            hi_b = F(b["max_ratio"]) if b.get("max_ratio") is not None else None
            ok_low = lo_b is None or ratio >= lo_b
            ok_high = hi_b is None or ratio < hi_b
            lo_ok.append(ok_low and ok_high)
        idx = next((i for i, ok in enumerate(lo_ok) if ok), len(brackets) - 1)
        br = brackets[idx]
    tax = amount * F(br["rate"]) - base * F(br["quick_deduct_pct"])
    return {
        "value": _clamp_nonneg(tax),
        "audit": {
            "ratio": ratio, "bracket": br,
            "formula": "增值额×率−扣除项目×速算系数",
        },
    }


# ---------------------------------------------------------------
# 5) compound -- 复合计税（从价 + 从量并行，卷烟/白酒类）
# ---------------------------------------------------------------
def compound(args, params):
    base = F(args["base"])
    qty = F(args["quantity"])
    tax = base * F(params["ad_valorem_rate"]) + qty * F(params["unit_tax"])
    return {
        "value": tax,
        "audit": {
            "formula": "从价 base×rate ＋ 从量 qty×unit",
            "base": base, "quantity": qty,
        },
    }


# ---------------------------------------------------------------
# 6) tiered_cliff -- 断崖式优惠（小型微利企业类）：
#    应纳税所得额 <= low_max 时全部按 low_rate；
#    一旦超过 low_max，全额回落 high_rate（优惠整体丧失）。
# ---------------------------------------------------------------
def tiered_cliff(args, params):
    base = F(args["base"])
    low_max = F(params["low_max"])
    if base <= low_max:
        tax, hit = base * F(params["low_rate"]), "低税率档"
    else:
        tax, hit = base * F(params["high_rate"]), "超限全额回归标准税率"
    return {"value": _clamp_nonneg(tax), "audit": {"hit": hit}}


DISPATCH = {
    "flat": flat,
    "multiply": multiply,
    "progressive": progressive,
    "super_progressive": super_progressive,
    "compound": compound,
    "tiered_cliff": tiered_cliff,
}
