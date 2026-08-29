# OpenTax — Open-Source Tax Calculation Engine

**Rules as data (YAML plugins) + zero-knowledge engine + deterministic scenario enumeration.**
The engine code contains no tax rates at all; all arithmetic runs on exact fractions; when a transaction date falls outside every rule's effective window, the engine **refuses to answer instead of guessing**.

> **Why this exists**: LLMs frequently give wrong answers on tax questions — policy version drift (old and new documents mixed in training data), language models don't actually do arithmetic (one drifted digit collapses the whole chain), and high-quality worked tax examples are scarce in public corpora. This project's answer is to **separate knowledge from computation**: the LLM listens and clarifies; this engine computes.

> **This is a foundation awaiting your data**: only a handful of core rules (currently China) are built in — the engine's capacity far exceeds the current dataset. The pillars are standing; the deck needs builders. **Contributions of tax data from ANY country are welcome**: statute citations with document numbers, official worked examples, real filed-return figures, sub-national variations, entire foreign tax systems. No programming needed — copy an existing YAML and fill in your numbers. See [CONTRIBUTING.md](CONTRIBUTING.md).

> 中文说明：[README_zh.md →](README_zh.md) — English version here.

---

## Three Iron Rules

1. **Change taxes only in YAML** — the engine knows zero tax law; rules are data plugins with legal citations and effective date ranges.
2. **Out-of-date = refuse** — every rule carries `effective` bounds and a first-hand source document number; a date outside every window throws `[REFUSED]` instead of computing.
3. **Dual-path self-verification** — progressive taxes are computed twice (bracket slicing AND quick-deduction formula); any mismatch raises immediately. This check has already caught one real data-entry error during development.

## Quick Start

```bash
python run_tests.py        # 25 golden tests

# Single rule: China land value-added tax (reproduces a real filed
# T20000 return: 64,099,828.80 CNY)
python -m open_tax single --date 2026-03-01 --rule cn/lvat/four_bracket \
    --set amount=106833048 --set base=0

# Pipeline waterfall: a 1.15M CNY construction contract -> owner's
# take-home 408,308.12, with a citation chain on every step.
# Missing required inputs produce a question list (exit code 3);
# uninvoiced costs automatically trigger a "collect invoices" warning.
python -m open_tax pipeline --pipeline engineering_to_owner \
    --date 2026-03-01 --set contract_gross=1150000 --set cost_invoiced=600000

# Scenario enumeration: invoice-timing optimization for the same
# contract (deterministic exhaustive search, not an AI opinion)
python -m open_tax enumerate --scenario withdrawal_strategy \
    --date 2026-03-01 --set contract_gross=1150000 --set cost_expense=900000
```

A real finding from enumeration (machine-discovered):

| Rank | Strategy | Take-home (CNY) |
|---|---|---|
| 1 | Spread invoicing evenly across 4 quarters (each under the 300k quarterly exemption line) | **190,455.45** |
| 2–4 | Lump / 2 / 3 quarters (every quarter over the line → taxed in full) | 180,308.12 |

Note: spreading over 2 or 3 quarters is **useless** — the exemption tests each period alone; only a full 4-quarter spread lands inside it. Exactly the kind of trap where guessing fails and enumeration doesn't.

## Rules Included (all with citations + effective ranges)

| Rule | Primitive | Source |
|---|---|---|
| China IIT annual comprehensive income table (7 brackets) | `progressive` w/ dual-path verification | Presidential Decree No. 9 |
| China IIT business income table (5 brackets) | `progressive` | Presidential Decree No. 9 |
| Dividend/interest 20% | `flat` | Presidential Decree No. 9 |
| Land value-added tax, 4-bracket super-progressive | `super_progressive` | State Council Decree No. 138 |
| Small-scale taxpayer VAT levy rate (3% base / reduced 1% window 2023–2027, auto-switching) | `flat`, multi-version | Caishui [2016] 36 / STA-SAT Announcement [2023] 19 |
| Small-scale quarterly ≤300k exemption (cliff: exceed once → taxed on the full amount) | `threshold_exempt` | Caishui [2019] 13 → [2023] 19 |
| Small low-profit CIT (≤3M at effective 5%, cliff back to 25%, through 2027-12-31) | `tiered_cliff` | Announcement [2023] 12 |
| Annual bonus separate taxation (÷12 bracket, cliff "blind zones" anchored at 36k/144k boundaries, through 2027-12-31) | `lump_bracket` | Caishui [2018] 164 |
| Tobacco chain: leaf tax 20% / Class-A & B production excise (56%/36% + 0.003/stick) / wholesale excise (11% + 250/carton) | `flat`/`compound` | Tobacco Leaf Tax Law; Caishui [2015] 60 |
| VAT on goods (17%→16%→13% multi-version, auto-selected by date) | `flat`, multi-version | VAT Regulations; Caishui [2018] 32; Announcement [2019] 39 |
| **US Federal IIT 2024** — Single & MFJ brackets + standard deductions (second-country sample: data only, zero engine changes) | `progressive` dual-path | IRS Rev. Proc. 2023-34 |
| **EU VAT** — 7 member states' standard rates (DE 19 / FR 20 / NL-ES 21 / IT 22 / PL 23 / SE 25) + reduced samples, per-country rule ids with national legal sources; cross-country price-decomposition scenario | `flat` | national statutes (UStG, CGI, DPR 633/72, Wet OB, Ley 37/92, Ustawa o VAT, ML 1994:200) |
| **Japan Consumption Tax** — one rule id, four historical versions on the time axis (3%→5%→8%→10%), auto-selected by transaction date; reduced 8% rate (food takeout/newspapers, since 2019-10); eat-in vs takeout comparison scenario | `flat`, 4-version timeline | 消費税法（昭和63年法律第108号）and partial amendments |

## Eight Primitives (enough to onboard any country)

`flat` (proportional) · `multiply` (data-driven adjustment) · `progressive` (marginal brackets + dual-path self-check) · `super_progressive` (rate-progressive, e.g. land VAT) · `compound` (ad valorem + per-unit, tobacco/alcohol) · `tiered_cliff` (cliff-edge relief) · `threshold_exempt` (threshold exemption) · `lump_bracket` (one-off income: ÷12 bracket with single quick-deduction — the annual-bonus "blind zone" structure)

Plus a price-split helper `price_split(gross_incl_tax, rate)`.

### Reconciling against official published examples

```bash
pip install pymupdf
python scripts/check_official_sources.py            # uses cached IRS PDF
python scripts/check_official_sources.py --refresh  # re-download from irs.gov
```

The script downloads the **official IRS 2024 Tax Table** and reconciles
engine output cell-by-cell. Fun fact it documents: the IRS table taxes
the **midpoint** of each $50 bracket and rounds half-up — which is why
the table says $13,847 where the exact formula gives $13,841. Both are
correct; the script bridges the conventions. Same pattern applies to
other jurisdictions' official examples (CN filing-instruction examples,
JP national tax agency booklets, EU Commission rate publications).

## Architecture

```
data/rules/<jurisdiction>/*.yaml   rule plugins (rates, windows, citations, verified_by)
data/pipelines/*.yaml              calculation waterfalls (steps reference the rule library)
data/scenarios/*.yaml              decision axes (enumerate combos, rank by result)
open_tax/engine/                   zero-knowledge core: primitives + versioning + audit trail
open_tax/cli.py                    CLI entry (bare-bones LLM orchestration layer)
tests/test_golden.py               official anchors + real-return regressions
.github/workflows/ci.yml           PR regression; weekly scan auto-files issues for expiring rules
```

Pipeline example (zero hard-coded rates — the levy rate is resolved from the rule library at run time by transaction date):

```yaml
- as: levy_rate
  op: param                      # resolves 0.01 inside the 2023–2027 window, else 0.03
  rule: cn/vat/small_goods
- as: vat_taxable
  op: expr
  expr: contract_gross / (1 + levy_rate)
```

## How to Contribute (Excel skills suffice)

1. **Report errors** (most welcome): open an Issue — rule ID, transaction date, expected vs actual, **source document number + official link**.
2. **Add rules**: a PR = one YAML file (copy any file under `data/rules/`) + one golden anchor test. Hard requirements:
   - statute / regulation / official-announcement-level first-hand source;
   - document number + effective range (use `null` if open-ended);
   - at least one official worked example or verifiable filed-return figure as the test anchor.
3. **Become a verifier**: sustained contributors get credited in `verified_by` — your professional brand attached to the rules you verify.

**Adding your country**: pick the closest primitive (see table above), write one YAML under `data/rules/<country>/`, add one test. If it doesn't fit a primitive, open an issue — the primitive set is small on purpose and grows only with a concrete use case.

## Roadmap

- [x] Engine + China four-tax full chain + scenario enumerator (current state)
- [x] Cigarette full-chain case (leaf tax → factory compound excise with in-tax back-solving → wholesale levy → VAT credit chain; teaches why cheap packs die on the fixed per-carton levy)
- [x] China annual-bonus separate taxation (lump_bracket primitive; blind-zone cliffs anchored; policy blank after 2027-12-31 refuses by design)
- [ ] Six-taxes-two-fees halving supplement pack; per-province local education surcharge versions
- [ ] **PRC catalog coverage: 8 of 18 statutory taxes** (VAT, CIT, IIT, land VAT, leaf tax, urban construction tax complete; consumption tax & stamp duty partial). Highest-value gaps for contributors, in order: 车辆购置税 vehicle purchase tax (10% flat — easiest first PR), 契税 deed tax (3–5% provincial variation — locality sample), 房产税 property tax (ad valorem 1.2% / rental 12%), full stamp-duty catalog (13 items), 车船税 vehicle & vessel tax (per-unit schedule). Customs/resource/environment taxes last (valuation & factor complexity).
- [x] **Second-country sample: US Federal IIT 2024** (Single/MFJ brackets + standard deductions + filing-status comparison scenario — added as YAML + tests only, proving "data only, no code changes"; 2025 parameters not yet included → out-of-scope refusal until contributed)
- [x] **EU VAT sample** — one jurisdiction, many countries: 7 member states' standard rates as independent rule ids with national legal citations; the price-decomposition scenario shows the same €100 price tag carries 15.97% (DE) to 20% (SE) VAT share
- [x] **Japan consumption tax sample** — the mirror image of EU: one rule id carrying four historical rate versions (3%→5%→8%→10%) on the time axis; the same pipeline walks 1989/1997/2014/2019 tax regimes by just changing the date; eat-in 10% vs takeout 8% scenario (the "eat-in war")
- [ ] LLM orchestration spec: mandatory parameter follow-ups; freshness statement on every output

## Disclaimer

Output is a tool-computed result, **for reference only — not tax advice and not a filing basis**. Tax treatment is strongly fact-dependent; consult a licensed professional for specific matters. Rule data must always yield to the currently-effective official text; found an error? Please open an Issue — we fix with test cases attached.

## License

MIT
