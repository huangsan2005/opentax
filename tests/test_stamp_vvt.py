"""产权转移书据 + 车船税（北京7档）golden —— 法条/官方表格复算。

来源核验（2026-08-28/29）：
  印花税法附表·产权转移书据：万分之五/万分之三（山西省税务局官方引文）
  车船税法附表·乘用车7档：区间全国统一，北京税额来自北京市税务局附件doc解析
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from open_tax.engine.calculator import Calculator, fmt     # noqa: E402
from open_tax.engine.primitives import TaxEngineError      # noqa: E402


def calc():
    return Calculator(rules_root=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "rules"))


class TestStampPropertyTransfer(unittest.TestCase):
    """印花税·产权转移书据（2022-07-01 起，法律级）。"""

    def test_house_transfer_2m(self):
        """房屋转让书据 200万（不含列明增值税）→ 万分之五 = 1,000。"""
        val, _ = calc().apply("cn/stamp/property_transfer_land_house_equity",
                              "2026-03-01", {"base": "2000000"})
        self.assertEqual(fmt(val), "1,000.00")

    def test_equity_transfer_500k(self):
        """股权转让书据 50万 → 万分之五 = 250。"""
        val, _ = calc().apply("cn/stamp/property_transfer_land_house_equity",
                              "2026-03-01", {"base": "500000"})
        self.assertEqual(fmt(val), "250.00")

    def test_ip_transfer_1m(self):
        """专利权转让 100万 → 万分之三 = 300。"""
        val, _ = calc().apply("cn/stamp/property_transfer_ip",
                              "2026-03-01", {"base": "1000000"})
        self.assertEqual(fmt(val), "300.00")

    def test_pre2022_refused(self):
        """印花税法 2022-07-01 施行，此前按暂行条例口径未入库 → 拒答。"""
        with self.assertRaises(TaxEngineError):
            calc().apply("cn/stamp/property_transfer_land_house_equity",
                         "2022-06-30", {"base": "1000000"})


class TestVehicleVesselTaxBeijing(unittest.TestCase):
    """车船税·乘用车7档（北京税额；法定区间见 notes）。"""

    AMOUNTS = {
        "cn/vvt/passenger_1L_below": ("300", "300.00"),
        "cn/vvt/passenger_1L_1p6": ("420", "420.00"),
        "cn/vvt/passenger_1p6_2L": ("480", "480.00"),
        "cn/vvt/passenger_2L_2p5": ("900", "900.00"),
        "cn/vvt/passenger_2p5_3L": ("1920", "1,920.00"),
        "cn/vvt/passenger_3L_4L": ("3480", "3,480.00"),
        "cn/vvt/passenger_4L_above": ("5280", "5,280.00"),
    }

    def test_all_seven_brackets(self):
        c = calc()
        for rid, (amount, want) in self.AMOUNTS.items():
            val, _ = c.apply(rid, "2026-03-01", {"base": amount})
            self.assertEqual(fmt(val), want, rid)

    def test_half_year_proration(self):
        """半年（base=amount/2）→ 北京1.6-2.0L档 480/2=240。"""
        val, _ = calc().apply("cn/vvt/passenger_1p6_2L", "2026-03-01",
                              {"base": "240"})
        self.assertEqual(fmt(val), "240.00")

    def test_pre2012_refused(self):
        """车船税法 2012-01-01 施行，此前暂行条例口径未入库 → 拒答。"""
        with self.assertRaises(TaxEngineError):
            calc().apply("cn/vvt/passenger_1L_1p6", "2011-12-31",
                         {"base": "420"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
