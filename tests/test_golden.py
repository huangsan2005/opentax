"""golden 测试：官方算例 + 双路径一致性 + 拒答行为。

每个用例注释标明数字来源；改任何 YAML 导致失败即为回归。
运行：python run_tests.py
"""
import os
import sys
import unittest
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from open_tax.engine.calculator import Calculator, fmt  # noqa: E402
from open_tax.engine.loader import load_all, resolve    # noqa: E402
from open_tax.engine.pipeline import run_pipeline       # noqa: E402
from open_tax.engine.primitives import (                # noqa: E402
    F,
    TaxEngineError,
)
from open_tax.engine.scenarios import (                 # noqa: E402
    enumerate_scenario,
    load_yaml_defs,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")

F0 = Fraction(0)


def calc():
    return Calculator(rules_root=os.path.join(DATA, "rules"))


class TestDataIntegrity(unittest.TestCase):
    """全库加载即校验（文号/生效期/原语合法性由 loader 强制）。"""

    def test_load_all_rules(self):
        reg = load_all(os.path.join(DATA, "rules"))
        self.assertGreaterEqual(len(reg), 8)

    def test_no_duplicate_version_conflict(self):
        reg = load_all(os.path.join(DATA, "rules"))
        for rid, versions in reg.items():
            seen = []
            for v in versions:
                key = (v["_start"], v["_end"], v.get("priority"))
                # 同区间同优先级视为冲突（同id同窗口应只登记一次）
                base_key = (v["_start"], v["_end"])
                if base_key in seen and (v.get("priority") or 0) == 0:
                    self.fail("%s 存在重复基础版本 %s" % (rid, base_key))
                seen.append(base_key)


class TestIITGolden(unittest.TestCase):
    """个税综合所得：官方速算扣除数口径的锚点值。

    来源：个人所得税法税率表一（主席令第九号），
    各档 上限×率−速算扣除数 应等于切片累加（引擎内部已双验）。
    """

    CASES = [
        ("36000", "1080"),
        ("144000", "11880"),
        ("300000", "43080"),
        ("420000", "73080"),
        ("660000", "145080"),
        ("960000", "250080"),
        ("1200000", "358080"),      # 1200000*0.45-181920（初版错写360480，
                                    # 引擎双路径互验当场抓出此测试数据错误）
    ]

    def test_bracket_anchors(self):
        c = calc()
        for amount, want in self.CASES:
            val, _ = c.apply("cn/iit/comprehensive_annual", "2026-03-01",
                             {"amount": amount})
            self.assertEqual(val, F(want), "amount=%s" % amount)

    def test_business_income(self):
        c = calc()
        val, _ = c.apply("cn/iit/business_income", "2026-03-01",
                         {"amount": "50000"})
        self.assertEqual(val, F("3500"))   # 50000*0.10-1500

    def test_out_of_scope_rejected(self):
        c = calc()
        with self.assertRaises(TaxEngineError):
            c.apply("cn/iit/comprehensive_annual", "2018-06-01",
                    {"amount": "100000"})   # 法2019年才施行


class TestLVATGolden(unittest.TestCase):
    """土增税：条例四档 + 速算系数，含 T20000 真实填报口径复现。"""

    def test_second_bracket(self):
        c = calc()
        # 增值额65万/扣除100万 => 65%档: 65×40%−100×5% = 21万
        val, _ = c.apply("cn/lvat/four_bracket", "2026-01-01",
                         {"amount": "650000", "base": "1000000"})
        self.assertEqual(val, F("210000"))

    def test_boundary_exactly_50pct_stays_lowest(self):
        c = calc()
        # 恰好50%（未"超过"）落第一档 30%
        val, _ = c.apply("cn/lvat/four_bracket", "2026-01-01",
                         {"amount": "500000", "base": "1000000"})
        self.assertEqual(val, F("150000"))

    def test_t20000_zero_deduction_case(self):
        c = calc()
        # 万事达法拍单 T20000 表：收入 106,833,048 扣除空 -> 顶格60%
        # 106833048 × 0.6 = 64,099,828.80 —— 与真实申报表互验
        val, _ = c.apply("cn/lvat/four_bracket", "2025-12-31",
                         {"amount": "106833048", "base": "0"})
        self.assertEqual(fmt(val), "64,099,828.80")


class TestVATAndSmallPolicy(unittest.TestCase):

    def test_price_split_5pct_round_number(self):
        # 开福区函件隐含：106,833,048 ÷1.05 为整数，税款恰为 5,087,288.00
        from open_tax.engine.primitives import price_split
        self.assertEqual(price_split(106833048, "0.05"),
                         F("5087288"))

    def test_cycle_exempt_below_threshold(self):
        c = calc()
        val, step = c.apply("cn/vat/small_cycle_exempt", "2026-03-01",
                            {"base": "290000"})
        self.assertEqual(val, F0)

    def test_cycle_exempt_above_threshold_full_cliff(self):
        c = calc()
        # 超线全额计税（非仅超额部分），且处于减按1%窗口
        val, _ = c.apply("cn/vat/small_cycle_exempt", "2026-03-01",
                         {"base": "310000"})
        self.assertEqual(val, F("3100"))     # 310000×1%

    def test_window_fallback_to_base_rate(self):
        c = calc()
        # 2019 年无减征窗口 -> 落基准版 3%
        tbl = resolve(load_all(os.path.join(DATA, "rules")),
                      "cn/vat/small_goods", "2019-06-15")
        self.assertEqual(tbl["params"]["rate"], "0.03")


class TestCITCliff(unittest.TestCase):

    def test_under_3m_effective_5pct(self):
        c = calc()
        val, _ = c.apply("cn/cit/small_low_profit", "2026-03-01",
                         {"base": "3000000"})
        self.assertEqual(val, F("150000"))

    def test_cliff_one_yuan_over(self):
        c = calc()
        # 超1元 -> 全额25%，这正是断崖残酷处
        val, _ = c.apply("cn/cit/small_low_profit", "2026-03-01",
                         {"base": "3000001"})
        self.assertEqual(val, F("750000.25"))


class TestSurtax(unittest.TestCase):
    def test_urban_construction(self):
        c = calc()
        val, _ = c.apply("cn/surtax/urban_7pct", "2026-03-01",
                         {"base": "110000"})
        self.assertEqual(val, F("7700"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
