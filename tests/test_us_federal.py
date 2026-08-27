"""US federal 2024 golden anchors — 切片手工复算（官方税表同构）。

所有锚点 = 逐档切片累加的独立手工复算，与引擎速算法互验；
2025 年度未收录，交易日期越界必须拒答。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from open_tax.engine.calculator import Calculator, fmt     # noqa: E402
from open_tax.engine.pipeline import run_pipeline          # noqa: E402
from open_tax.engine.primitives import TaxEngineError      # noqa: E402
from open_tax.engine.scenarios import (                    # noqa: E402
    enumerate_scenario,
    load_yaml_defs,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")


def calc():
    return Calculator(rules_root=os.path.join(DATA, "rules"))


class TestUSSingle(unittest.TestCase):
    """Single，标准扣除 14,600（Rev. Proc. 2023-34）。"""

    def test_50000_wages(self):
        """wages 50,000 → taxable 35,400：
        11,600×10% + 23,800×12% = 1,160 + 2,856 = 4,016"""
        r = run_pipeline(self._pipes()["us_federal_iit_single"],
                         "2024-12-31", {"gross_wages": "50000"})
        self.assertEqual(fmt(r["federal_income_tax"]), "4,016.00")
        self.assertEqual(fmt(r["taxable_income"]), "35,400.00")

    def test_100000_wages_into_22pct(self):
        """wages 100,000 → taxable 85,400：
        1,160 + 4,266 + (85,400−47,150)×22% = 1,160+4,266+8,415 = 13,841"""
        r = run_pipeline(self._pipes()["us_federal_iit_single"],
                         "2024-12-31", {"gross_wages": "100000"})
        self.assertEqual(fmt(r["federal_income_tax"]), "13,841.00")

    def test_itemized_beats_standard(self):
        """分项 20,000 > 标准 14,600 → taxable = 50,000−20,000 = 30,000：
        11,600×10% + 18,400×12% = 1,160 + 2,208 = 3,368
        （初版测试注释误把 15,400 当应税额——引擎切片法复算纠错）"""
        r = run_pipeline(self._pipes()["us_federal_iit_single"],
                         "2024-12-31",
                         {"gross_wages": "50000", "itemized": "20000"})
        self.assertEqual(fmt(r["federal_income_tax"]), "3,368.00")

    def test_low_income_below_std_deduction(self):
        """wages 10,000 < 标准扣除 → taxable 0 → tax 0。"""
        r = run_pipeline(self._pipes()["us_federal_iit_single"],
                         "2024-12-31", {"gross_wages": "10000"})
        self.assertEqual(fmt(r["federal_income_tax"]), "0.00")

    def _pipes(self):
        from open_tax.engine.scenarios import load_yaml_defs
        return load_yaml_defs(os.path.join(DATA, "pipelines"))


class TestUSMFJ(unittest.TestCase):
    """MFJ，标准扣除 29,200。"""

    def _pipes(self):
        from open_tax.engine.scenarios import load_yaml_defs
        return load_yaml_defs(os.path.join(DATA, "pipelines"))

    def test_150000_wages(self):
        """wages 150,000 → taxable 120,800：
        23,200×10%=2,320; (94,300−23,200)×12%=8,532;
        (120,800−94,300)×22%=5,830 → 合计 16,682"""
        r = run_pipeline(self._pipes()["us_federal_iit_mfj"],
                         "2024-12-31", {"gross_wages": "150000"})
        self.assertEqual(fmt(r["federal_income_tax"]), "16,682.00")

    def test_marriage_bonus_or_penalty_visible(self):
        """同收入 150,000：MFJ 税 < Single 税（两倍标准扣除+宽档）。
        Single 150,000 → taxable 135,400: 1,160+4,266+
        (100,525−47,150)×22%+... 切片=  1,160+4,266+11,742.50+
        (135,400−100,525)×24%=8,370 → 25,538.50"""
        pipes = self._pipes()
        single = run_pipeline(pipes["us_federal_iit_single"],
                              "2024-12-31", {"gross_wages": "150000"})
        mfj = run_pipeline(pipes["us_federal_iit_mfj"],
                           "2024-12-31", {"gross_wages": "150000"})
        self.assertLess(float(mfj["federal_income_tax"]),
                        float(single["federal_income_tax"]))


class TestUSBoundaries(unittest.TestCase):
    def test_2025_refused(self):
        """2025 税务年度未收录（参数尚未入库）→ 拒答。"""
        with self.assertRaises(TaxEngineError):
            calc().apply("us/federal/iit_2024_single", "2025-04-15",
                         {"amount": "50000"})

    def test_filing_status_enumeration(self):
        """场景枚举跑通：两行、MFJ 税更低（值比较而非名次）。"""
        scen = load_yaml_defs(os.path.join(DATA, "scenarios"))
        pipes = load_yaml_defs(os.path.join(DATA, "pipelines"))
        rows = enumerate_scenario(scen["us_filing_status_compare"],
                                  pipes, "2024-12-31",
                                  {"gross_wages": "150000"})
        self.assertEqual(len(rows), 2)
        by_label = {" ".join(r["combo"]): r for r in rows}
        single = next(v for k, v in by_label.items()
                      if "Single" in k and "Married" not in k)
        mfj = next(v for k, v in by_label.items() if "Married" in k)
        self.assertLess(float(mfj["result"]),
                        float(single["result"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
