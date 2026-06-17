# Reynoso for Congress — donor cross-reference

Cross-references the donors across **Reynoso for Congress's** 2026 FEC itemized-receipts
filings (Dec 2025 – June 2026, merged and de-duplicated by transaction) against every other
campaign-finance dataset on hand — **Andrew Cuomo's** mayoral
campaign, the **NYC + NY-State independent-expenditure** committees, and **AIPAC & allied
PACs** (2023–24 and 2025–26) — and flags who the campaign refunded.

## Outputs
| File | What |
|---|---|
| **`public/index.html`** | The report — interactive (search, filters, committee links). ← deliverable |

## Regenerate
```sh
python3 build_report.py        # rebuilds public/index.html from data/
```

## Refresh the AIPAC federal data
`fetch_pac_receipts.py` pulls 2025–26 receipts for AIPAC PAC, UDP, NORPAC, DMFI and RJC
from the FEC API into `data/aipac-2026/`. Needs a free key from api.data.gov:
```sh
export FEC_API_KEY=...          # https://api.data.gov/signup/  (1,000 req/hr)
python3 fetch_pac_receipts.py   # resumable; writes the combined receipts CSV
```

## Data (`data/`)
| Folder | Source | Contents |
|---|---|---|
| `reynoso-fec/` | FEC — Reynoso for Congress | June receipts (`efile-…17_15_38`), disbursements/refunds (`…17_20_50`), earlier `schedule_a` |
| `nyc-cfb/` | NYC Campaign Finance Board | Cuomo mayoral file (`…155734714`) + 2025 IE/PAC filers (`…144614138`, `…151634515`) |
| `ny-state-boe/` | NY State Board of Elections | 5 independent-expenditure contribution/loan exports |
| `aipac/` | AIPAC & Allies 2023–2024 | single donor CSV |
| `aipac-2026/` | FEC — AIPAC PAC, UDP, NORPAC, DMFI, RJC (2025–26) | single combined CSV (56,581 rows) |

## How matching works
- A Reynoso donor is matched to an outside record by **name**, then **confirmed** only
  when the **full 9-digit ZIP** *or* the **employer** also agrees — name alone is never
  enough. (Street address would be stronger but the FEC exports carry no street field.)
- Same-name records that confirm by neither ZIP nor employer are treated as **different
  people**: excluded from every total and **not shown**.
- **AIPAC** records are split per (committee, ZIP, employer) so two same-name donors
  (e.g. two Daniel Lowys) stay separable — only the matching one is counted.
- **NYC-CFB and NY-State** report the same 2025 mayoral IE committees, so those figures
  are **de-duplicated by committee (max of the two), not added**.
- **Refunds** (Schedule 20A) carry only a last name + ZIP; each is tied to one donor by
  full ZIP, with household ties broken by date. Every refunded donor is listed.

## Config knobs (top of `build_report.py`)
- **`EXCLUDE_DISPLAY`** — committees dropped from the analysis (currently: New Yorkers for
  Lower Costs, OneNYC, New York for Ray, Moving NY Families Forward, Hudson Valley Voters,
  Brooklyn Bridgebuilders, New York Deserves Better PAC, WFP NYS-IE, Latino Victory Fund
  NYC, New York Women Lead, Verrazzano Victory Alliance, Our City). Add a name to drop it.
- **`MANUAL_CONFIRM`** — donors whose identity is vouched for despite ZIP/employer not
  auto-confirming (e.g. Michael Kempner = MWW / MikeWorldWide).
- **`PAC_REFS`** — committee → article-URL links rendered in the report.
- Cuomo-only matches **under $1,000** are dropped as low-signal unless the donor was refunded.

## Report layout
`public/index.html`: **topline** (Reynoso's take from Cuomo / Fix-the-City donors
and from AIPAC & allied donors) → per-donor **cards** (each donor's gift to Reynoso plus their
footprint across Cuomo, the IE/PAC committees, and AIPAC, with live search/filters) →
**IE / PAC committees most funded** by these donors.
