# -*- coding: utf-8 -*-
"""官方来源对账：IRS 2024 Tax Table / Tax Computation Worksheet vs OpenTax.

从 IRS 官方 PDF（2024 Tax Table）提取真实税额单元格，与引擎输出对账：
  * Tax Table（应税所得 < $100k）：IRS 按每 $50 区间中点计税、半元进位。
    桥接公式：irs_cell == floor(engine(lo + 25) + 0.5)
  * Tax Computation Worksheet（>= $100k）：即引擎的速算扣除公式，点值精确。

用法：
    python scripts/check_official_sources.py            # 用本地缓存 PDF
    python scripts/check_official_sources.py --refresh  # 重新下载官方 PDF

依赖：pymupdf（pip install pymupdf）；引擎无额外依赖。
"""
import math
import os
import subprocess
import sys
import urllib.request

import fitz  # pymupdf

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, ".tmp_verify", "taxtable2024.pdf")
URL = "https://www.irs.gov/pub/irs-prior/i1040tt--2024.pdf"

CHECKS = [
    # (label, taxable, col, rule, mode)
    ("Single  wage 50k -> ti 35,400", 35400, 0,
     "us/federal/iit_2024_single", "midpoint"),
    ("Single  wage 100k -> ti 85,400", 85400, 0,
     "us/federal/iit_2024_single", "midpoint"),
    ("MFJ     wage 150k -> ti 120,800", 120800, 1,
     "us/federal/iit_2024_mfj", "worksheet"),
]


def ensure_pdf(refresh=False):
    if os.path.exists(CACHE) and not refresh:
        return CACHE
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    print("downloading official IRS Tax Table ...")
    urllib.request.urlretrieve(URL, CACHE)
    print("cached:", CACHE)
    return CACHE


def engine_tax(rule, ti, date="2024-12-31"):
    r = subprocess.run(
        [sys.executable, "-m", "open_tax", "single", "--date", date,
         "--rule", rule, "--set", f"amount={ti}"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    line = [l for l in r.stdout.splitlines() if l.startswith("结果")]
    return float(line[-1].split("：")[1].replace(",", ""))


def parse_rows(page):
    words = page.get_text("words")
    rows = {}
    for x0, y0, x1, y1, w, *_ in words:
        w = w.replace(",", "")
        if w.isdigit():
            y = round(y0 / 4) * 4
            rows.setdefault(y, []).append((x0, int(w)))
    return [[v for _, v in sorted(rows[y])] for y in sorted(rows)]


def extract_table(pdf_path):
    doc = fitz.open(pdf_path)
    table = {}
    for pno in range(1, len(doc)):
        for cells in parse_rows(doc[pno]):
            for i in range(len(cells) - 5):
                six = cells[i:i + 6]
                lo, hi = six[0], six[1]
                taxes = six[2:6]
                if (hi - lo == 50 and len(taxes) == 4
                        and all(c <= lo for c in taxes)):
                    table.setdefault(lo, (taxes, pno + 1))
    return table


def main():
    refresh = "--refresh" in sys.argv
    pdf = ensure_pdf(refresh)
    table = extract_table(pdf)
    print(f"tax table rows parsed: {len(table)}")

    print("\n=== IRS official sources vs OpenTax engine ===")
    ok = True
    for label, ti, col, rule, mode in CHECKS:
        eng = engine_tax(rule, ti)
        if mode == "midpoint":
            if ti not in table:
                print(f"{label}: TABLE ROW MISSING")
                ok = False
                continue
            irs_val, page = table[ti][0][col], table[ti][1]
            bridged = engine_tax(rule, ti + 25)
            predicted = math.floor(bridged + 0.5)
            status = "MATCH" if predicted == irs_val else "DIFF"
            if predicted != irs_val:
                ok = False
            print(f"{label}\n    IRS table cell: {irs_val:>7,} (p.{page})"
                  f"\n    engine @{ti}: {eng:,.2f}"
                  f"\n    engine @midpoint {ti + 25}: {bridged:,.2f}"
                  f" -> half-up {predicted:,}  [{status}]")
        else:  # worksheet: point-exact quick-deduction formula
            hand = 120800 * 0.22 - 9894   # MFJ 22% 档速算公式
            status = "MATCH" if abs(eng - hand) < 0.01 else "DIFF"
            if abs(eng - hand) >= 0.01:
                ok = False
            print(f"{label}\n    Tax Computation Worksheet: "
                  f"120800 x 22% - 9894 = {hand:,.2f}"
                  f"\n    engine @{ti}: {eng:,.2f}  [{status}]"
                  f"   (>= $100k 用 Worksheet，非 Tax Table)")

    print("\nVERDICT:",
          "ALL MATCH - engine reconciles with official IRS sources"
          if ok else "DIFFERENCES FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
