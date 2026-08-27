"""日本消費税 golden —— 时间轴穿越锚点（同 id 四版本自动选版）。

价税分离复算：税 = 税込÷(1+率)×率。
"""
import os
import sys
import unittest
from fractions import Fraction

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


class TestJPTimeline(unittest.TestCase):
    """同 id 四版本：交易日即时光机（3%→5%→8%→10%）。"""

    TIMELINE = [
        ("1989-04-01", "0.03"),   # 导入日
        ("1997-03-31", "0.03"),   # 3% 末日
        ("1997-04-01", "0.05"),   # 5% 首日
        ("2014-03-31", "0.05"),   # 8% 前夜
        ("2014-04-01", "0.08"),   # 8% 首日
        ("2019-09-30", "0.08"),   # 10% 前夜
        ("2019-10-01", "0.10"),   # 10% 首日
        ("2026-08-28", "0.10"),   # 现行
    ]

    def test_rate_by_date(self):
        c = calc()
        from open_tax.engine.loader import resolve
        for d, want in self.TIMELINE:
            t = resolve(c.registry, "jp/consumption_tax/standard", d)
            self.assertEqual(t["params"]["rate"], want, d)

    def test_pre1989_refused(self):
        """消費税 1989 年才存在：1988 年拒答。"""
        with self.assertRaises(TaxEngineError):
            calc().apply("jp/consumption_tax/standard", "1988-06-15",
                         {"base": "1000"})

    def test_reduced_only_post2019(self):
        """軽減税率 2019-10 起才有：2019-09-30 引用即拒答。"""
        with self.assertRaises(TaxEngineError):
            calc().apply("jp/consumption_tax/reduced_food", "2019-09-30",
                         {"base": "1000"})


class TestJPPipeline(unittest.TestCase):
    """同一条管线，四个时代四种结果。"""

    def setUp(self):
        self.pipes = load_yaml_defs(os.path.join(DATA, "pipelines"))

    def run_split(self, date, gross="1100"):
        return run_pipeline(self.pipes["japan_ct_price_split"],
                            date, {"gross_price": gross})

    def test_same_price_four_eras(self):
        """1100 円价签：3%→32.04 / 5%→52.38 / 8%→81.48 / 10%→100.00。"""
        cases = [
            ("1990-06-01", "32.04"),   # 1100÷1.03×0.03=32.0388...
            ("1997-06-01", "52.38"),   # 1100÷1.05×0.05=52.3809...
            ("2015-06-01", "81.48"),   # 1100÷1.08×0.08=81.4814...
            ("2020-06-01", "100.00"),  # 1100÷1.10×0.10=100
        ]
        for d, want in cases:
            r = self.run_split(d)
            self.assertEqual(fmt(r["ct_amount"]), want, d)

    def test_round_trip_identity(self):
        r = self.run_split("2020-06-01", "9791")
        self.assertEqual(r["net_price"] + r["ct_amount"],
                         Fraction("9791"))

    def test_share_equals_rate_over_rate_plus_one(self):
        """含税占比 = rate/(1+rate)：10% → 100/11 = 9.0909...%"""
        r = self.run_split("2020-06-01")
        self.assertEqual(r["ct_share_pct"],
                         Fraction("0.10") / Fraction("1.10") * 100)


class TestJPEatInScenario(unittest.TestCase):
    def test_takeout_cheaper_than_eat_in(self):
        """同一 1100 円弁当：外带 8% 税额 < 堂食 10% 税额。"""
        scen = load_yaml_defs(os.path.join(DATA, "scenarios"))
        pipes = load_yaml_defs(os.path.join(DATA, "pipelines"))
        rows = enumerate_scenario(scen["jp_eat_in_vs_takeout"], pipes,
                                  "2026-03-01", {"gross_price": "1100"})
        self.assertEqual(len(rows), 2)
        eat_in = next(r for r in rows if "堂食" in ",".join(r["combo"]))
        takeout = next(r for r in rows if "外带" in ",".join(r["combo"]))
        self.assertGreater(float(eat_in["result"]),
                           float(takeout["result"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
