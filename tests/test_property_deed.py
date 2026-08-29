"""车辆购置税/契税/房产税 golden —— 锚点全部为官方法条公式复算。

法条依据（fgk.chinatax.gov.cn 法规库原文，2026-08-28 核验）：
  车购税法第四/五/六条：税=不含税价×10%
  契税法第三条：3%-5% 幅度（本表存下限3%），省级版本待补
  房产税条例第三/四条：从价=原值×(1-减除)×1.2%；从租=租金×12%
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from open_tax.engine.calculator import Calculator, fmt     # noqa: E402
from open_tax.engine.pipeline import run_pipeline          # noqa: E402
from open_tax.engine.primitives import TaxEngineError      # noqa: E402
from open_tax.engine.scenarios import load_yaml_defs       # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")


def calc():
    return Calculator(rules_root=os.path.join(DATA, "rules"))


class TestVehiclePurchaseTax(unittest.TestCase):
    """车购税法：税 = 不含增值税价款 × 10%。"""

    def test_113000_gross(self):
        """含税购车 113,000 → 不含税 100,000 → 税 10,000。
        （第六条（一）：计税价格不含增值税，13% 价税分离）"""
        val, _ = calc().apply("cn/vpt/base", "2026-03-01",
                              {"base": "100000"})
        self.assertEqual(fmt(val), "10,000.00")

    def test_one_time_only_note(self):
        """法条口径：一次性征收（第三条）——不建年度重复条目，
        二次交易不触发本税。此处验证引擎条目本身可拒答历史日期。"""
        with self.assertRaises(TaxEngineError):
            calc().apply("cn/vpt/base", "2019-06-30", {"base": "100000"})


class TestDeedTax(unittest.TestCase):
    """契税法：3%-5% 幅度，省级决定。引擎存法定下限 3%。"""

    def test_floor_rate_3pct(self):
        val, _ = calc().apply("cn/deed_tax/base", "2026-03-01",
                              {"base": "1000000"})
        self.assertEqual(fmt(val), "30,000.00")

    def test_pre2021_refused(self):
        """契税法 2021-09-01 施行，此前暂行条例版本未入库 → 拒答。"""
        with self.assertRaises(TaxEngineError):
            calc().apply("cn/deed_tax/base", "2021-08-31",
                         {"base": "1000000"})


class TestPropertyTax(unittest.TestCase):
    """房产税条例：从价余值1.2%（减除比例 inputs 传入）；从租12%。"""

    def test_ad_valorem_with_30pct_deduction(self):
        """原值 2,000,000，省定减除 30% → 余值 1,400,000 × 1.2% = 16,800
        （余值由调用方按条例第三条算好，规则层只承载 1.2% 税率）"""
        val, _ = calc().apply("cn/property_tax/ad_valorem", "2026-03-01",
                              {"base": "1400000"})
        self.assertEqual(fmt(val), "16,800.00")

    def test_ad_valorem_ratio_is_caller_side(self):
        """同一原值，减除比例改 10%（某省口径）→ 余值 1,800,000×1.2% = 21,600"""
        val, _ = calc().apply("cn/property_tax/ad_valorem", "2026-03-01",
                              {"base": "1800000"})
        self.assertEqual(fmt(val), "21,600.00")

    def test_rental_12pct(self):
        """年租金 120,000 → 从租 12% = 14,400"""
        val, _ = calc().apply("cn/property_tax/rental", "2026-03-01",
                              {"base": "120000"})
        self.assertEqual(fmt(val), "14,400.00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
