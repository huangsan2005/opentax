"""六大确定性原语 -- 引擎不知道任何具体税种名称。

每个函数返回 {"value": Fraction, "audit": {...}}，
由 calculator 层包装成统一审计步骤。

设计约束：
- 一切数值经 Fraction(str(...)) 进入，杜绝二进制浮点污染；
- 任何中间结果可追溯：audit 里保留公式与匹配到的档位。
"""
from fractions import Fraction


class TaxEngineError(Exception):
    """引擎基础异常。"""


class OutOfScope(TaxEngineError):
    """交易日期没有命中任何规则版本 --> 拒绝作答。"""

    def __init__(self, rule_id, tx_date, windows):
        self.rule_id = rule_id
        self.tx_date = tx_date
        self.windows = windows
        ranges = "; ".join(
            "%s 至 %s" % (w[0] or "?", w[1] or "至今") for w in windows
        )
        super().__init__(
            "[拒答] %s 在 %s 无有效版本（已收录：%s）。"
            "数据超出内置范围时不做推测。" % (rule_id, tx_date, ranges)
        )


def F(v):
    """int/str/Fraction -> Fraction 安全转换。"""
    if isinstance(v, Fraction):
        return v
    return Fraction(str(v))


def _clamp_nonneg(x):
    return x if x > 0 else Fraction(0)


# ---------------------------------------------------------------
# 1) flat -- 比例税率（城建税/附加/股息红利/印花税类）
# ---------------------------------------------------------------
def flat(args, params):
    """
    args:   base 计税基础; deduct 可选固定减免
    params: rate 必填
    公式:   tax = max(0, base × rate - deduct)
    """
    base = F(args["base"])
    rate = F(params["rate"])
    deduct = F(args.get("deduct", 0))
    tax = base * rate - deduct
    return {
        "value": _clamp_nonneg(tax),
        "audit": {
            "formula": "base×rate−deduct",
            "base": base,
            "rate": rate,
            "deduct": deduct,
        },
    }


# ---------------------------------------------------------------
# 2) multiply -- 数据驱动的调整（减半征收、减按25%计入等）
# ---------------------------------------------------------------
def multiply(args, params):
    val = F(args["value"]) * F(params["factor"])
    return {"value": val, "audit": {"formula": "value×factor"}}


# ---------------------------------------------------------------
# 3) progressive -- 超额累进（个人所得税类）。
#    内置双路径互验：逐档切片累加 与 速算扣除公式，二者必须一致。
# ---------------------------------------------------------------
def progressive(args, params):
    amount = F(args["amount"])
    brackets = params["brackets"]
    if amount <= 0:
        return {"value": Fraction(0),
                "audit": {"note": "amount<=0", "slices": []}}

    # 路径A：逐档切片
    sliced = Fraction(0)
    slices = []
    lo = Fraction(0)
    for b in brackets:
        hi_v = b.get("max_amount")
        hi = F(hi_v) if hi_v is not None else None
        rate = F(b["rate"])
        if amount > lo:
            upper = amount if hi is None else min(amount, hi)
            if upper > lo:
                seg = (upper - lo) * rate
                sliced += seg
                slices.append({
                    "range_lo": str(lo),
                    "range_hi": str(hi) if hi is not None else None,
                    "portion_in_bracket": str(upper - lo),
                    "rate": str(rate),
                    "tax_slice": str(seg),
                })
        if hi is None or amount <= hi:
            break
        lo = hi

    # 路径B：速算扣除数公式
    br = None
    for b in brackets:
        hi_v = b.get("max_amount")
        if hi_v is None or amount <= F(hi_v):
            br = b
            break
    if br is None:
        raise TaxEngineError("progressive: 未匹配到税级")
    quick_total = amount * F(br["rate"]) - F(br.get("quick_deduct", 0))

    if sliced != quick_total:
        raise TaxEngineError(
            "[内部一致性破坏] %s 切片法=%s != 速算法=%s -- 请上报规则数据错误"
            % (br.get("parent", ""), sliced, quick_total)
        )
    return {
        "value": quick_total,
        "audit": {
            "matched_bracket": {k: br.get(k) for k in ("max_amount", "rate",
                                                       "quick_deduct")},
            "slices": slices,
            "consistency": "切片累加 == 速算扣除 ✓",
        },
    }


# ---------------------------------------------------------------
# 4) super_progressive -- 超率累进（土地增值税类）
#    增值率 = 增值额 ÷ 扣除项目金额；档位公式：
#    应纳税额 = 增值额×税率 − 扣除项目×速算扣除系数
#    扣除项目=0 时增值率视同无穷大（T20000 表填报口径），落最高档。
# ---------------------------------------------------------------
def super_progressive(args, params):
    amount = F(args["amount"])       # 增值额
    base = F(args["base"])           # 扣除项目金额
    brackets = params["brackets"]
    if amount <= 0:
        return {"value": Fraction(0), "audit": {"note": "增值额<=0"}}

    if base == 0:
        ratio = None
        br = brackets[-1]
        matched = "扣除项目为0，视同增值率无穷大 -> 最高档"
    else:
        ratio = amount / base
        br = None
        for b in brackets:
            lo_b = F(b["min_ratio"]) if b.get("min_ratio") is not None else None
            hi_b = F(b["max_ratio"]) if b.get("max_ratio") is not None else None
            ok_low = lo_b is None or ratio >= lo_b
            ok_high = hi_b is None or ratio < hi_b
            if ok_low and ok_high:
                br = b
                break
        if br is None:
            raise TaxEngineError("super_progressive: 增值率 %s 未命中档位" % ratio)
        matched = "增值率=%.4f" % ratio
    tax = amount * F(br["rate"]) - base * F(br["quick_deduct_pct"])
    return {
        "value": _clamp_nonneg(tax),
        "audit": {
            "matched": matched,
            "ratio": str(ratio) if ratio is not None else "inf",
            "bracket": {k: br.get(k) for k in ("min_ratio", "max_ratio",
                                               "rate", "quick_deduct_pct")},
            "formula": "增值额×率 − 扣除项目×速算系数",
        },
    }


# ---------------------------------------------------------------
# 5) compound -- 复合计税（从价+从量并行：卷烟/白酒类）
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
#    base <= low_max 时全部按 low_rate；一旦超过，全额回归 high_rate。
#    （低档全有或全无，非累进切分 -- 这是小微政策实证结构）
# ---------------------------------------------------------------
def tiered_cliff(args, params):
    base = F(args["base"])
    low_max = F(params["low_max"])
    low_rate = F(params["low_rate"])
    high_rate = F(params["high_rate"])
    if base <= low_max:
        tax, hit = base * low_rate, "低税率档 (base %s <= %s)" % (base, low_max)
    else:
        tax, hit = base * high_rate, ("断崖！base %s 超过 %s，全额回归标准税率"
                                      % (base, low_max))
    return {"value": _clamp_nonneg(tax), "audit": {"hit": hit}}


# ---------------------------------------------------------------
# 7) threshold_exempt -- 起征点式免征（小微增值税月销售≤X 万全额免税类）
#    base <= threshold 时税额为 0；一旦超过，全额计税（非超额部分）。
# ---------------------------------------------------------------
def threshold_exempt(args, params):
    base = F(args["base"])
    threshold = F(params["threshold"])
    if base <= threshold:
        return {"value": Fraction(0),
                "audit": {"hit": "免税档 (base %s <= %s)" % (base, threshold)}}
    tax = base * F(params["rate"])
    return {"value": tax,
            "audit": {"hit": "超阈值全额计税 (%s > %s)" % (base, threshold),
                      "rate": params["rate"]}}


DISPATCH = {
    "flat": flat,
    "multiply": multiply,
    "progressive": progressive,
    "super_progressive": super_progressive,
    "compound": compound,
    "tiered_cliff": tiered_cliff,
    "threshold_exempt": threshold_exempt,
}


# ---------------------------------------------------------------
# price_split -- 中国增值税价税分离辅助（非独立原语，管线算子用）
#   含税价 B、征收率 r：税款 = B ÷(1+r)×r；不含税 = B − 税款
# ---------------------------------------------------------------
def price_split(base, rate, part="tax"):
    base, rate = F(base), F(rate)
    tax = base / (1 + rate) * rate
    return tax if part == "tax" else base - tax
