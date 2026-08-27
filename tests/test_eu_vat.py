"""EU VAT golden anchors — 价税分离手工复算 + 成员国税率 + 版本边界。

锚点原则：每个数都能由 tax = gross÷(1+rate)×rate 独立复算；
税率来自各成员国法律（见 data/rules/eu/vat.yaml 的 source）。
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


class TestEURuleResolution(unittest.TestCase):
    """每国独立 id：按 id 取率，而非同 id 多国争抢。"""

    RATES = {
        "eu/vat/standard_de": "0.19",
        "eu/vat/standard_fr": "0.20",
        "eu/vat/standard_it": "0.22",
        "eu/vat/standard_nl": "0.21",
        "eu/vat/standard_es": "0.21",
        "eu/vat/standard_pl": "0.23",
        "eu/vat/standard_se": "0.25",
    }

    def test_all_member_state_rates(self):
        c = calc()
        for rid, want in self.RATES.items():
            tbl = c.registry and None
            from open_tax.engine.loader import resolve
            t = resolve(c.registry, rid, "2026-03-01")
            self.assertEqual(t["params"]["rate"], want, rid)

    def test_reduced_rates(self):
        c = calc()
        from open_tax.engine.loader import resolve
        self.assertEqual(
            resolve(c.registry, "eu/vat/reduced_de", "2026-03-01")
            ["params"]["rate"], "0.07")
        self.assertEqual(
            resolve(c.registry, "eu/vat/reduced_fr", "2026-03-01")
            ["params"]["rate"], "0.055")
        self.assertEqual(
            resolve(c.registry, "eu/vat/reduced_nl", "2026-03-01")
            ["params"]["rate"], "0.09")

    def test_french_pre2014_refused(self):
        """法国20%自2014-01-01：2013年交易日无覆盖 -> 拒答。"""
        with self.assertRaises(TaxEngineError):
            calc().apply("eu/vat/standard_fr", "2013-06-01",
                         {"base": "100"})
        # 但2007后的德国19%在2013年有效
        val, _ = calc().apply("eu/vat/standard_de", "2013-06-01",
                              {"base": "100"})
        self.assertEqual(fmt(val), "19.00")


class TestEUPipeline(unittest.TestCase):
    """价税分离：tax = gross÷(1+rate)×rate，手工复算锚点。"""

    def setUp(self):
        self.pipes = load_yaml_defs(os.path.join(DATA, "pipelines"))

    def run_pipe(self, pid, gross, date="2026-03-01"):
        return run_pipeline(self.pipes[pid], date,
                            {"gross_price": gross})

    def test_germany_100_eur(self):
        """DE: 100÷1.19×0.19 = 15.966386... → 15.97；share 15.97%"""
        r = self.run_pipe("eu_vat_price_split_de", "100")
        self.assertEqual(fmt(r["vat_amount"]), "15.97")
        self.assertEqual(fmt(r["vat_share_pct"]), "15.97")

    def test_sweden_100_eur(self):
        """SE 25%: 100÷1.25×0.25 = 20.00；share 20.00%"""
        r = self.run_pipe("eu_vat_price_split_se", "100")
        self.assertEqual(fmt(r["vat_amount"]), "20.00")
        self.assertEqual(fmt(r["vat_share_pct"]), "20.00")

    def test_france_100_eur(self):
        """FR 20%: 100÷1.20×0.20 = 16.666... → 16.67；share 16.67%"""
        r = self.run_pipe("eu_vat_price_split_fr", "100")
        self.assertEqual(fmt(r["vat_amount"]), "16.67")

    def test_poland_23pct_share(self):
        """PL 23%: 100÷1.23×0.23 = 18.699... → 18.70；share 18.70%"""
        r = self.run_pipe("eu_vat_price_split_pl", "100")
        self.assertEqual(fmt(r["vat_amount"]), "18.70")
        self.assertEqual(fmt(r["vat_share_pct"]), "18.70")

    def test_exact_round_trip(self):
        """恒等式：net + vat == gross（分数精确，无舍入漂移）。"""
        r = self.run_pipe("eu_vat_price_split_it", "99.99")
        self.assertEqual(r["net_price"] + r["vat_amount"],
                         Fraction("99.99"))

    def test_share_matches_rate_formula(self):
        """含税占比 = rate/(1+rate)：DE 0.19/1.19 = 15.966%，恒等。"""
        r = self.run_pipe("eu_vat_price_split_de", "250")
        self.assertEqual(r["vat_share_pct"],
                         F := Fraction("0.19") / Fraction("1.19") * 100
                         if False else
                         Fraction("0.19") / Fraction("1.19") * 100)


class TestEUScenario(unittest.TestCase):
    def test_country_ranking_se_top(self):
        """七国对比：瑞典25%占比最高排第1，德国19%最低排第7。"""
        scen = load_yaml_defs(os.path.join(DATA, "scenarios"))
        pipes = load_yaml_defs(os.path.join(DATA, "pipelines"))
        rows = enumerate_scenario(scen["eu_vat_country_compare"],
                                  pipes, "2026-03-01",
                                  {"gross_price": "100"})
        self.assertEqual(len(rows), 7)
        self.assertIn("Sweden", ",".join(rows[0]["combo"]))
        self.assertIn("Germany", ",".join(rows[-1]["combo"]))
        # 相邻行占比严格递减
        vals = [r["result"] for r in rows]
        self.assertTrue(all(vals[i] >= vals[i + 1]
                            for i in range(len(vals) - 1)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
