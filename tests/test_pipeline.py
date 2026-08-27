"""管线与场景枚举测试：工程款瀑布 & 开票节奏寻优。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from open_tax.cli import main as cli_main
from open_tax.engine.calculator import fmt              # noqa: E402
from open_tax.engine.pipeline import (
    MissingInputs,
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
                          "cost_invoiced": "600000"})
        # 手工核对（1%窗口）：不含税=1138613.86；增值税=11386.14；
        # 附加12%=1366.34；所得额=537247.52→企税26862.38；
        # 可分配=1150000−11386.14−1366.34−600000−26862.38=510385.15；
        # 分红税20%=102077.03；到手=408308.12
        self.assertEqual(fmt(r["owner_net"]), "408,308.12")

    def test_uninvoiced_cost_not_deductible(self):
        """无票成本不得税前扣除（28号公告）：等额抬高所得额。
        真实代价 = 损失的抵税权，而非成本本身：
        200,000 × 5%(小微档) × 80%(分红口径) = 8,000 元。
        （若越过300万断崖则按25%计：代价 = 200,000×25%×80% = 40,000）
        本金两种情形都已真实支出，不构成额外差额。
        """
        base = {"contract_gross": "1150000", "cost_invoiced": "400000",
                "cost_uninvoiced": "200000"}
        r = run_pipeline(self.pipelines["engineering_to_owner"],
                         self.date, base)
        clean = run_pipeline(self.pipelines["engineering_to_owner"],
                             self.date,
                             {"contract_gross": "1150000",
                              "cost_invoiced": "600000"})
        # 与600000全有票对比：所得额多200000 -> 企税多10000（5%档）
        self.assertEqual(fmt(r["cit_payable"]),
                         fmt(clean["cit_payable"] + 10000))
        # 到手差 = 多缴企税10000 × 80% = 8000
        self.assertEqual(fmt(r["owner_net"]),
                         fmt(clean["owner_net"] - 8000))

    def test_missing_inputs_asks_questions(self):
        """追问协议：缺 required 参数 -> MissingInputs 携带问题清单。"""
        try:
            run_pipeline(self.pipelines["engineering_to_owner"],
                         self.date, {"cost_invoiced": "600000"})
            self.fail("应当抛出 MissingInputs")
        except MissingInputs as mi:
            self.assertEqual(len(mi.questions), 1)
            self.assertIn("合同额", mi.questions[0])

    def test_uninvoiced_note_triggered(self):
        """无票成本>0 时输出催票警示，并引用文号与汇算清缴时点。"""
        r = run_pipeline(self.pipelines["engineering_to_owner"],
                         self.date,
                         {"contract_gross": "1150000",
                          "cost_invoiced": "600000",
                          "cost_uninvoiced": "50000"})
        notes = [s for s in r.steps if s.get("is_note")]
        self.assertEqual(len(notes), 1)
        self.assertIn("2018年第28号", notes[0]["flag"])
        self.assertIn("5月31日", notes[0]["flag"])

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

    def test_cli_missing_inputs_exit_code_3(self):
        """CLI 追问协议：缺参数返回码3 + 问题文本（LLM 编排层契约）。"""
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli_main(["pipeline", "--pipeline",
                             "engineering_to_owner", "--date", "2026-03-01",
                             "--set", "cost_invoiced=600000"])
        self.assertEqual(code, 3)
        # 追问清单只含 required 参数的问题（无票成本为可选输入，不强制问）
        self.assertIn("合同额", buf.getvalue())


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
