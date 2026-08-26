"""管线与场景枚举测试：工程款瀑布 & 开票节奏寻优。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from open_tax.engine.calculator import fmt              # noqa: E402
from open_tax.engine.pipeline import (
    run_pipeline,
    safe_eval,
)
from open_tax.engine.scenarios import (                 # noqa: E402
    enumerate_scenario,
    load_yaml_defs,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")


class TestSafeEval(unittest.TestCase):
    def test_arithmetic_ok(self):
        self.assertEqual(safe_eval("a * b + 1", {"a": "2", "b": "3"}),
                         __import__("fractions").Fraction(7))

    def test_comparison_returns_flag(self):
        self.assertEqual(safe_eval("x <= 300000", {"x": "299999"}),
                         __import__("fractions").Fraction(1))

    def test_injection_blocked(self):
        with self.assertRaises(Exception):
            safe_eval("__import__('os').system('dir')", {})


class TestEngineeringPipeline(unittest.TestCase):
    def setUp(self):
        self.pipelines = load_yaml_defs(
            os.path.join(DATA, "pipelines"))
        self.date = "2026-03-01"

    def test_snapshot_waterfall(self):
        r = run_pipeline(self.pipelines["engineering_to_owner"],
                         self.date,
                         {"contract_gross": "1150000",
                          "cost_expense": "600000"})
        # 手工核对（1%窗口）：不含税=1138613.86；增值税=11386.14；
        # 附加12%=1366.34；所得额=537247.52→企税26862.38；
        # 可分配=1150000−11386.14−1366.34−600000−26862.38=510385.15；
        # 分红税20%=102077.03；到手=408308.12
        self.assertEqual(fmt(r["owner_net"]), "408,308.12")

    def test_staged_vs_lump_vat_gap(self):
        """四季均匀开票可全额免增值税；集中单季开票要交税+附加。
        同时验证二阶效应：附加税费可在企税前扣除，故免税会抬高企税基数。
        """
        common = {"contract_gross": "1150000", "cost_expense": "900000"}
        spread = run_pipeline(self.pipelines["engineering_to_owner_staged"],
                              self.date, dict(common, n_periods="4"))
        lump = run_pipeline(self.pipelines["engineering_to_owner_staged"],
                            self.date, dict(common, n_periods="1"))
        # 四季均匀：每季不含税284,653.47 ≤30万 -> 免税
        self.assertEqual(fmt(spread["vat_total"]), "0.00")
        # 集中单季：1,138,613.86 >30万 -> 全额1%
        self.assertEqual(fmt(lump["vat_total"]), "11,386.14")
        # 二阶效应（精确）：spread 免掉附加138000/101 -> 扣除减少 ->
        # 企税多缴 6900/101 元，非直觉的"企税不受影响"
        from fractions import Fraction
        self.assertEqual(spread["cit_total"] - lump["cit_total"],
                         Fraction(6900, 101))
        # 净效果仍显著：到手差 = (免增值税+免附加−多缴企税)×80%
        #   = (1150000+138000−6900)/101 × 0.8 = 1024880/101 ≈ 10,147.33
        self.assertEqual(spread["owner_net"] - lump["owner_net"],
                         Fraction(1024880, 101))
        self.assertGreater(float(spread["owner_net"]),
                           float(lump["owner_net"]))


class TestScenarioEnumeration(unittest.TestCase):
    def test_withdrawal_ranking(self):
        scen = load_yaml_defs(os.path.join(DATA, "scenarios"))
        pipes = load_yaml_defs(os.path.join(DATA, "pipelines"))
        rows = enumerate_scenario(scen["withdrawal_strategy"], pipes,
                                  "2026-03-01",
                                  {"contract_gross": "1150000",
                                   "cost_expense": "900000"})
        self.assertEqual(len(rows), 4)
        # 排名第一必须是分散开票方案（合法节奏下的确定性最优）
        best = ",".join(rows[0]["combo"])
        self.assertIn("四季均匀", best)
        # 表格渲染不抛异常且包含免责声明
        text = rows.render()
        self.assertIn("不构成税务建议", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
