"""新增 golden：年终奖单独计税（lump_bracket + 盲区）与卷烟全链条。

锚点原则：只用可溯源数字——官方文号公式复算、管线内部恒等式、
结构性事实。网传"14.89%/37.23%"无官方算例出处，不作为锚点；
"税负占比 30-70%"这类拍脑袋区间同样不入测试（低价包实际远超此区间，
因为 250元/条从量税=5元/包 是与售价无关的固定负担）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from open_tax.engine.calculator import Calculator, fmt     # noqa: E402
from open_tax.engine.pipeline import (                      # noqa: E402
    TaxEngineError,
    run_pipeline,
)
from open_tax.engine.scenarios import load_yaml_defs       # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")


def calc():
    return Calculator(rules_root=os.path.join(DATA, "rules"))


class TestAnnualBonus(unittest.TestCase):
    """财税〔2018〕164号：÷12找档全额累进；档位边界盲区锚点。"""

    def test_36000_at_third_bracket(self):
        # 36000÷12=3000，"不超过3000元"档含边界 -> 3%：税 1080
        val, _ = calc().apply("cn/iit/annual_bonus", "2026-03-01",
                              {"amount": "36000"})
        self.assertEqual(fmt(val), "1,080.00")

    def test_36001_blind_zone_jump(self):
        """多1元奖金 -> 跳10%档、速算只减一次：税 3,390.10，
        比 36,000 时多缴 2,310.10 元——盲区的直观呈现。"""
        c = calc()
        v_low, _ = c.apply("cn/iit/annual_bonus", "2026-03-01",
                           {"amount": "36000"})
        v_high, step = c.apply("cn/iit/annual_bonus", "2026-03-01",
                               {"amount": "36001"})
        self.assertEqual(fmt(v_high), "3,390.10")   # 36001×10%−210
        self.assertEqual(step["detail"]["quota"], "36001/12")
        self.assertGreater(float(v_high - v_low), 2000)

    def test_144000_bracket_boundary(self):
        """144000÷12=12000，"超过3000至12000"档含12000 -> 10%：
        144000×0.10−210=14,190；多1元跳20%：144001×0.20−1410=27,390.20。"""
        c = calc()
        v, _ = c.apply("cn/iit/annual_bonus", "2026-03-01",
                       {"amount": "144000"})
        self.assertEqual(fmt(v), "14,190.00")
        v2, _ = c.apply("cn/iit/annual_bonus", "2026-03-01",
                        {"amount": "144001"})
        self.assertEqual(fmt(v2), "27,390.20")

    def test_policy_expires_2028(self):
        """2028-01-01起政策空白占位 -> 拒答而非静默用过期口径。"""
        with self.assertRaises(TaxEngineError):
            calc().apply("cn/iit/annual_bonus", "2028-03-01",
                         {"amount": "36000"})


class TestCigaretteChain(unittest.TestCase):
    """卷烟全链条：官方公式 + 恒等式 + 结构性事实作为锚点。"""

    def setUp(self):
        self.pipes = load_yaml_defs(os.path.join(DATA, "pipelines"))

    def run_chain(self, retail_gross, **over):
        inputs = {"retail_gross": retail_gross}
        inputs.update({k: str(v) for k, v in over.items()})
        return run_pipeline(self.pipes["cigarette_chain"],
                            "2026-03-01", inputs)

    def test_single_stage_formulas_official(self):
        """单环节公式（财税〔2015〕60号文直接复算）："""
        c = calc()
        # 甲类生产：100元出厂、20支 -> 100×0.56+20×0.003 = 56.06
        v, _ = c.apply("cn/cig_production_class_a", "2026-03-01",
                       {"base": "100", "quantity": "20"})
        self.assertEqual(fmt(v), "56.06")
        # 批发：85元×0.11 + 250元/条 = 259.35（每条口径）
        v2, _ = c.apply("cn/cig_wholesale", "2026-03-01",
                        {"base": "85", "quantity": "1"})
        self.assertEqual(fmt(v2), "259.35")
        # 烟叶税法：3元×0.20 = 0.60
        v3, _ = c.apply("cn/tobacco_leaf", "2026-03-01", {"base": "3"})
        self.assertEqual(fmt(v3), "0.60")

    def test_backsolving_identity_and_positive_vat(self):
        """价内税解方程恒等式成立；各环节增值税均为正（增值额口径）。"""
        r = self.run_chain("45")
        self.assertEqual(fmt(r["factory_excl"] + r["factory_excise"]),
                         fmt(r["factory_with_excise"]))
        self.assertGreater(float(r["wholesale_vat"]), 0)
        self.assertGreater(float(r["factory_vat"]), 0)
        self.assertGreater(float(r["retail_vat"]), 0)

    def test_specific_tax_is_price_invariant(self):
        """结构性事实：批发从量税 250元/条 与售价无关 -> 每包恒为 5 元。"""
        for price in ("20", "45", "100"):
            r = self.run_chain(price)
            self.assertEqual(fmt(r["wholesale_excise"]
                                 - r["wholesale_excl"] * 0.11),
                             "5.00")

    def test_excise_dominates_vat(self):
        """结构性事实：消费税类（烟叶+两道消费税）> 增值税合计。"""
        for price in ("45", "100"):
            r = self.run_chain(price)
            self.assertGreater(float(r["excise_total"]),
                               float(r["vat_total"]))

    def test_total_tax_rises_with_price(self):
        """绝对税额随售价单调上升（每包含税额），占比结构另论。"""
        t20 = float(self.run_chain("20")["total_tax"])
        t100 = float(self.run_chain("100")["total_tax"])
        self.assertGreater(t100, t20)

    def test_breakeven_refusal(self):
        """出厂价低于成本 -> 保本断言拒答（拒绝不成立的经济假设）。"""
        with self.assertRaises(TaxEngineError):
            self.run_chain("10", leaf_cost="3", other_cost="2",
                           wholesale_margin="4", retail_margin="3")

    def test_vat_rates_versioned(self):
        """链条里增值税率按交易日取版本：2026->13%，2016-01->17%。"""
        r = run_pipeline(self.pipes["cigarette_chain"], "2016-01-15",
                         {"retail_gross": "45"})
        self.assertEqual(fmt(r["vat_rate"] * 100), "17.00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
