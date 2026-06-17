#!/usr/bin/env python3
"""Master cross-reference: take Reynoso for Congress's latest itemized-contributions
e-filing and, for each donor, show their full footprint across every other dataset:
  - Andrew Cuomo's NYC mayoral campaign (data/nyc-cfb/CFB_...155734714.csv)
  - NYC + NY-State independent-expenditure / PAC committees
        (data/nyc-cfb/CFB_...138 + ...515, data/ny-state-boe/IndependentExpenditures*.csv)
  - AIPAC & allied PACs (data/aipac/AIPAC & Allies 2023-2024 Donor Data 2.0)
  - whether the Reynoso campaign REFUNDED them (data/reynoso-fec/efile-...17_20_50.csv, Sch. 20A)

The NYC-CFB and NY-State-BOE systems both report the 2025 mayoral IE committees, so
those are merged and de-duplicated by committee (max of the two reported figures) to
avoid double-counting. Emits public/index.html (interactive)."""
import csv, re, glob, json, os
from collections import defaultdict
from datetime import datetime

SUBJECT = 'data/reynoso-fec/efile-2026-06-16T17_15_38.csv'   # June 2026 itemized receipts
SCHED_A = 'data/reynoso-fec/schedule_a-2026-06-16T14_45_28.csv'  # earlier itemized receipts
CUOMO   = 'data/nyc-cfb/CFB_20260616155734714.csv'
CFB_PAC = ['data/nyc-cfb/CFB_20260616144614138.csv', 'data/nyc-cfb/CFB_20260616151634515.csv']
AIPAC   = 'data/aipac/AIPAC & Allies 2023-2024 Donor Data 2.0 - data (2023-2024).csv'
STATE   = sorted(glob.glob('data/ny-state-boe/IndependentExpenditures*.csv'))
DISB    = 'data/reynoso-fec/efile-2026-06-16T17_20_50.csv'

ORG_KW = re.compile(r'\b(LLC|INC|L\.?P\.?|LTD|CORP|PAC|FUND|UNION|LOCAL|COUNCIL|COMMITTEE|'
                    r'ASSOC|ASSOCIATION|COMPANY|PARTNERS|REALTY|GROUP|HOLDINGS|SEIU|LECET|'
                    r'DISTRICT|FEDERATION|BUILDING|PROPERTIES|MANAGEMENT|CAPITAL|ENTERPRISES|'
                    r'FOUNDATION|TRUST|SOCIETY|TEAMSTERS|CONSTRUCTION|HOTEL|TRADES|NYSNA|DCC|UFT)\b', re.I)
SUF = {'JR', 'SR', 'II', 'III', 'IV', 'V', 'MD', 'PHD', 'ESQ'}
AIPAC_SHORT = {
    'AMERICAN ISRAEL PUBLIC AFFAIRS COMMITTEE POLITICAL ACTION COMMITTEE': 'AIPAC PAC',
    'REPUBLICAN JEWISH COALITION-POLITICAL ACTION COMMITTEE (RJC-PAC)': 'RJC PAC',
    'NORPAC': 'NORPAC',
    "UNITED DEMOCRACY PROJECT ('UDP')": 'United Democracy Project (AIPAC super PAC)',
    'DMFI PAC': 'DMFI PAC',
    'RJC VICTORY FUND': 'RJC Victory Fund',
}
# IE committees excluded from the analysis: donors whose only outside footprint is one
# of these drop off the report entirely. Add a committee here to exclude it; EXCLUDE_PACS
# (the match set) and the report footer are derived from this list automatically.
EXCLUDE_DISPLAY = [
    'New Yorkers for Lower Costs',
    'OneNYC',
    'New York for Ray',
    'Moving New York Families Forward',
    'Hudson Valley Voters',
    'Brooklyn Bridgebuilders',
    'New York Deserves Better PAC',
    'Working Families Party PAC-NYS IE',
    'Latino Victory Fund NYC',
    'New York Women Lead',
    'Verrazzano Victory Alliance',
    'Our City',
]
# Extra spelling variants to also match (not shown separately in the footer):
EXCLUDE_VARIANTS = ['WFP National PAC - NYS IE Committee']

# Manually vouched-for identities: donors whose cross-dataset match is confirmed by
# outside knowledge even though ZIP/employer don't auto-confirm. Keyed ('IND', LAST, FIRST).
# Michael Kempner: Reynoso "Not Employed/10001" = MWW / MikeWorldWide founder (Cuomo + DMFI, 10021).
MANUAL_CONFIRM = {('IND', 'KEMPNER', 'MICHAEL')}

# Source citations for specific committees: the committee name links to this URL
# wherever it appears (interactive cards, IE/PAC summary table, and the PDF).
PAC_REFS = {
    'Next NYC PAC': 'https://x.com/WillBredderman/status/2036077681222057985',
    'Fix the City, Inc.': 'https://www.politico.com/newsletters/new-york-playbook/2025/05/13/cuomos-very-very-super-pac-00343806',
    'New Yorkers For A Better Future 2025': 'https://truthout.org/articles/these-billionaires-have-already-spent-19-million-in-a-bid-to-defeat-mamdani/',
    'Sensible City, Inc.': 'https://truthout.org/articles/these-billionaires-have-already-spent-19-million-in-a-bid-to-defeat-mamdani/',
    'Stand Up NYC': 'https://www.nyccfb.info/vsapps/IndependentSpenderSummary.aspx?spender_id=Z216&as_election_cycle=2025&cand_name=Stand%20Up%20NYC',
    'Moving Harlem Forward': 'https://www.cityandstateny.com/politics/2026/06/cheat-sheet-super-pacs-2026-new-york-primaries/414191/',
    'Protect the Protectors': 'https://www.nyccfb.info/vsapps/IndependentSpenderSummary.aspx?spender_id=Z233&as_election_cycle=2025&cand_name=Protect%20the%20Protectors',
}

def is_org(s): return bool(ORG_KW.search(s)) or bool(re.search(r'\d', s))
def nc(name):                                   # "LAST, FIRST"
    s = re.sub(r'\s+', ' ', name.upper().replace('.', ' ').replace('"', '')).strip()
    if not s or s in ('CONTRIBUTOR NAME', 'NAME'):
        return None
    if ',' in s:
        last, rest = s.split(',', 1); t = rest.strip().split()
        return ('IND', last.strip(), t[0] if t else '')
    return ('ORG', s, '')
def ns(name):                                   # "FIRST LAST"
    s = re.sub(r'\s+', ' ', name.upper().replace('.', ' ').replace('"', '').replace(',', ' ')).strip()
    if not s:
        return None
    if is_org(s):
        return ('ORG', re.sub(r'\s+', ' ', name.upper().strip()), '')
    t = [x for x in s.split() if x not in SUF]
    return ('IND', t[-1], t[0]) if len(t) >= 2 else ('ORG', s, '')
def kfl(last, first):                           # split first/last fields
    last = re.sub(r'\s+', ' ', (last or '').upper().replace('.', ' ')).strip()
    ft = (first or '').upper().replace('.', ' ').split()
    return ('IND', last, ft[0] if ft else '') if last else None
def fnum(x):
    x = re.sub(r'[^0-9.\-]', '', str(x or ''))
    try:
        return float(x) if x not in ('', '-', '.') else 0.0
    except ValueError:
        return 0.0
def z5(z): return (z or '')[:5]
def zd(z): return re.sub(r'\D', '', z or '')     # all zip digits
def zip_match(refz, subz):
    """True if zips agree. Compare full 9 digits when BOTH have them (so the +4
    distinguishes two people sharing a 5-digit ZIP); otherwise fall back to 5."""
    rd, sd_ = zd(refz), zd(subz)
    if len(rd) >= 9 and len(sd_) >= 9:
        return rd[:9] == sd_[:9]
    return rd[:5] == sd_[:5]
def ckey(name):                                 # committee-dedup key across reporting systems
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Z0-9 ]', ' ', name.upper())).strip()

EXCLUDE_PACS = {ckey(n) for n in (EXCLUDE_DISPLAY + EXCLUDE_VARIANTS)}

def yr(v):                                       # first 4 digits -> year string, else ''
    v = str(v or '').strip()[:4]
    return v if v.isdigit() else ''
def fmt_years(years):                            # set of year strings -> compact label
    ys = sorted({y for y in years if y})
    if not ys:
        return ''
    if len(ys) <= 2:
        return ', '.join(ys)
    return f'{ys[0]}–{ys[-1]}'              # range when 3+
def _fmtday(s):
    try:
        return datetime.strptime((s or '')[:10], '%Y-%m-%d').strftime('%b %-d, %Y')
    except ValueError:
        return ''
def fmt_dates(dates):                            # set of YYYY-MM-DD -> single date or range
    ds = sorted({d[:10] for d in dates if d})
    if not ds:
        return ''
    lo, hi = _fmtday(ds[0]), _fmtday(ds[-1])
    if lo == hi:
        return lo + (f' ({len(dates)}×)' if len(dates) > 1 else '')
    return f'{lo} – {hi}'

# ---------- subject donors: ALL Reynoso itemized receipts (June e-file + earlier
# schedule_a), de-duplicated by FEC transaction_id so an overlapping contribution
# reported in both filings is counted once. JUNE_KEYS marks who is in the June filing. ----------
subj = defaultdict(lambda: {'amt': 0.0, 'rows': 0, 'zip': '', 'zip9': '', 'mindate': '',
                            'dates': set(), 'city': '', 'st': '', 'emp': '', 'occ': '', 'names': set()})
JUNE_KEYS = set()
_seen_txn = set()
for _path, _is_june in ((SUBJECT, True), (SCHED_A, False)):
    with open(_path, newline='') as f:
        for r in csv.DictReader(f):
            if r.get('entity_type') != 'IND':
                continue
            if (r.get('contributor_last_name') or '').strip().upper() == 'ACTBLUE':
                continue
            k = kfl(r['contributor_last_name'], r['contributor_first_name'])
            if not k:
                continue
            if _is_june:
                JUNE_KEYS.add(k)
            txn = r.get('transaction_id')
            if txn and txn in _seen_txn:                 # same contribution in both filings
                continue
            if txn:
                _seen_txn.add(txn)
            d = subj[k]
            d['amt'] += fnum(r['contribution_receipt_amount']); d['rows'] += 1
            d['names'].add(f"{r['contributor_first_name']} {r['contributor_last_name']}".strip())
            if not d['zip']:
                d['zip'], d['city'], d['st'] = z5(r['contributor_zip']), r['contributor_city'], r['contributor_state']
            if not d['zip9']: d['zip9'] = r['contributor_zip']
            dt = r['contribution_receipt_date']
            if dt and (not d['mindate'] or dt < d['mindate']): d['mindate'] = dt
            if dt: d['dates'].add(dt[:10])
            if not d['emp']: d['emp'] = r['contributor_employer']
            if not d['occ']: d['occ'] = r['contributor_occupation']
SUBJECT_COUNT = len(subj)

# ---------- external arenas ----------
GENERIC_EMP = {'', 'SELFEMPLOYED', 'SELF', 'NOTEMPLOYED', 'NONE', 'NA', 'RETIRED', 'HOMEMAKER',
               'UNEMPLOYED', 'NOTAPPLICABLE', 'INFORMATIONREQUESTED', 'REQUESTED', 'BESTEFFORTS',
               'REFUSED', 'NOTPROVIDED', 'STUDENT', 'PRIVATEINVESTOR', 'INVESTOR'}
def emp_norm(e):
    s = re.sub(r'[^A-Z0-9]', '', (e or '').upper())
    return '' if s in GENERIC_EMP or len(s) < 4 else s
def emp_match(a, b):
    na, nb = emp_norm(a), emp_norm(b)
    return bool(na and nb) and (na == nb or na in nb or nb in na)
def emp_any(e, emps):                            # does donor employer match any in a set of normalized employers?
    ne = emp_norm(e)
    return bool(ne) and any(ne == x or ne in x or x in ne for x in emps if x)

cuomo = defaultdict(lambda: {'amt': 0.0, 'zip': '', 'years': set(), 'emps': set()})
ie    = defaultdict(lambda: {'pacs': {}, 'zip': '', 'emps': set()})   # merged NYC-CFB + NY-State, deduped by ckey
# AIPAC contributions kept per (committee, full-zip, employer) so same-name different-person
# records (e.g. two Daniel Lowys) stay separable and are matched by ZIP *or* employer.
aip   = defaultdict(lambda: {'groups': defaultdict(lambda: {'amt': 0.0, 'years': set()})})

with open(CUOMO, newline='') as f:
    for r in csv.DictReader(f):
        k = nc(r['NAME'])
        if not k: continue
        cuomo[k]['amt'] += fnum(r['AMNT'])
        if not cuomo[k]['zip']: cuomo[k]['zip'] = z5(r['ZIP'])
        if yr(r.get('ELECTION')): cuomo[k]['years'].add(yr(r['ELECTION']))
        if emp_norm(r.get('EMPNAME')): cuomo[k]['emps'].add(emp_norm(r['EMPNAME']))

def add_ie(k, disp, amt, src, zp, year='', emp=''):
    # Accumulate per (committee, source). Within a source, distinct gifts SUM;
    # across the two reporting systems we later take the MAX (same money mirrored).
    ck = ckey(disp)
    if ck in EXCLUDE_PACS:
        return
    d = ie[k]
    e = d['pacs'].get(ck)
    if e is None:
        e = d['pacs'][ck] = {'disp': disp.strip(), 'src_amts': defaultdict(float), 'years': set()}
    e['src_amts'][src] += amt
    if year: e['years'].add(year)
    if not d['zip'] and zp: d['zip'] = zp
    if emp_norm(emp): d['emps'].add(emp_norm(emp))

for path in CFB_PAC:
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            k = nc(r['NAME'])
            if not k: continue
            add_ie(k, r['RECIPNAME'], fnum(r['AMNT']), 'NYC CFB', z5(r['ZIP']), yr(r.get('ELECTION')), r.get('EMPNAME'))
seen = set()
for path in STATE:
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            key = (r['Candidate/Committee Name'], r['Contributor/Lender Name'],
                   r['Date Received'], r['Amount'], r['Contributor/Lender Address'])
            if key in seen: continue
            seen.add(key)
            k = ns(r['Contributor/Lender Name'])
            if not k: continue
            zz = re.findall(r'\b(\d{5})\b', r['Contributor/Lender Address'] or '')
            add_ie(k, r['Candidate/Committee Name'], fnum(r['Amount']), 'NY State',
                   zz[-1] if zz else '', yr(r.get('Year Received')), r.get('Contributor / Lender Employer'))

def add_aip(k, short, amt, zp, year, emp):
    g = aip[k]['groups'][(short, zp or '', emp_norm(emp))]   # split by full zip + employer
    g['amt'] += amt
    if year: g['years'].add(year)

# AIPAC & allies — 2023-24 file, then the 2025-26 FEC pull (if fetched into data/aipac-2026/)
with open(AIPAC, newline='') as f:
    for r in csv.DictReader(f):
        k = nc(r['contributor_name'])
        if not k: continue
        add_aip(k, AIPAC_SHORT.get(r['committee_name'], r['committee_name']),
                fnum(r['contribution_receipt_amount']), r.get('contributor_zip'),
                yr(r.get('report_year')), r.get('contributor_employer'))
AIPAC_2026 = sorted(glob.glob('data/aipac-2026/*receipts*.csv'))
for path in AIPAC_2026:
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            k = nc(r.get('contributor_name', ''))
            if not k: continue
            add_aip(k, AIPAC_SHORT.get(r.get('committee_name', ''), r.get('committee_name', '')),
                    fnum(r.get('contribution_receipt_amount')), r.get('contributor_zip'),
                    yr(r.get('report_year') or r.get('two_year_transaction_period')), r.get('contributor_employer'))

# Contribution refunds (Sch. 20A). The disbursement file gives only a LAST name +
# ZIP, so attribute each refund to exactly one subject donor: require full-ZIP
# agreement, and break household ties (e.g. two Lowys at one address) by date —
# the refunded gift must predate the refund. Refunds to people not in this filing
# stay unattributed and are counted for disclosure.
refund_rows = []
with open(DISB, newline='') as f:
    for r in csv.DictReader(f):
        if not r['line_number'].startswith('20A'): continue
        refund_rows.append({'last': re.sub(r'\s+', ' ', r['recipient_name'].upper().replace('.', ' ')).strip(),
                            'zip': r['recipient_zip'], 'amt': fnum(r['disbursement_amount']),
                            'date': r['disbursement_date'], 'city': r['recipient_city']})

refund_by_key = defaultdict(float)
refund_dates_by_key = defaultdict(list)
refund_unmatched = []
for rr in refund_rows:
    cands = [k for k in subj if k[1] == rr['last'] and zip_match(rr['zip'], subj[k]['zip9'] or subj[k]['zip'])]
    if not cands:
        refund_unmatched.append(rr)
        continue
    def rank(k):
        sd = subj[k]
        date_ok = 1 if (sd['mindate'] and rr['date'] and sd['mindate'] <= rr['date']) else 0
        amt_ok = 1 if abs(sd['amt'] - rr['amt']) < 0.01 else 0
        return (-date_ok, -amt_ok, sd['mindate'] or '9999')   # prefer gift-before-refund, then amount, then earliest
    best = sorted(cands, key=rank)[0]
    refund_by_key[best] += rr['amt']
    refund_dates_by_key[best].append(rr['date'])

# ---------- join ----------
def conf_of(subzip, srczip): return bool(subzip) and subzip == srczip
records = []
for k, sd in subj.items():
    rec = {'buckets': {}}
    if k in cuomo:
        rec['buckets']['cuomo'] = {'amt': round(cuomo[k]['amt'], 2),
                                   'conf': conf_of(sd['zip'], cuomo[k]['zip']) or emp_any(sd['emp'], cuomo[k]['emps']),
                                   'years': fmt_years(cuomo[k]['years'])}
    if k in ie:
        items = []
        for p in ie[k]['pacs'].values():
            amt = max(p['src_amts'].values())   # cross-system max; intra-system already summed
            items.append({'disp': p['disp'], 'amt': amt,
                          'src': ' + '.join(sorted(p['src_amts'].keys())), 'years': fmt_years(p['years'])})
        items.sort(key=lambda x: -x['amt'])
        rec['buckets']['ie'] = {
            'total': round(sum(p['amt'] for p in items), 2),
            'conf': conf_of(sd['zip'], ie[k]['zip']) or emp_any(sd['emp'], ie[k]['emps']),
            'pacs': [{'name': p['disp'], 'amt': round(p['amt'], 2), 'src': p['src'], 'years': p['years']} for p in items],
        }
    if k in aip:
        subz = sd['zip9'] or sd['zip']
        conf_p, name_p = {}, {}
        for (short, gz, ge), v in aip[k]['groups'].items():
            same = zip_match(subz, gz) or emp_match(sd['emp'], ge)   # ZIP or employer confirms identity
            tgt = conf_p if same else name_p
            e = tgt.setdefault(short, {'amt': 0.0, 'years': set()})
            e['amt'] += v['amt']; e['years'] |= v['years']
        use, conf = (conf_p, True) if conf_p else (name_p, False)    # drop different-person records when we have a confirmed one
        items = sorted(use.items(), key=lambda x: -x[1]['amt'])
        rec['buckets']['aipac'] = {
            'total': round(sum(v['amt'] for _, v in items), 2),
            'conf': conf,
            'pacs': [{'name': n, 'amt': round(v['amt'], 2), 'years': fmt_years(v['years'])} for n, v in items],
        }
    refund = refund_by_key.get(k, 0.0)
    if not rec['buckets'] and not refund:
        continue
    # Drop low-signal Cuomo-only matches: the only outside footprint is a sub-$1,000
    # gift to Cuomo (no IE/PAC or AIPAC tie) and the campaign did not refund them.
    if (set(rec['buckets']) == {'cuomo'}
            and rec['buckets']['cuomo']['amt'] < 1000
            and not refund):
        continue
    if k in MANUAL_CONFIRM:                        # vouched-for identity (e.g. Kempner / MWW)
        for b in rec['buckets'].values():
            b['conf'] = True
    # MAIN list (and totals) requires at least one ZIP/employer-confirmed match, or a refund.
    # Donors whose every match is name-only are demoted and excluded from the totals.
    confirmed = bool(refund) or any(b.get('conf') for b in rec['buckets'].values())
    rec.update({
        'display': ' / '.join(sorted(n.title() if n.isupper() else n for n in sd['names'])),
        'loc': f"{sd['city'].title()}, {sd['st']} {sd['zip']}".strip(),
        'occ': (sd['occ'] or '').strip().title(),
        'emp': (sd['emp'] or '').strip().title(),
        'rey_amt': round(sd['amt'], 2),
        'rey_dates': fmt_dates(sd['dates']),
        'refund': round(refund, 2),
        'refund_dates': fmt_dates(refund_dates_by_key.get(k, [])),
        'n_arenas': len(rec['buckets']),
        'offfiling': k not in JUNE_KEYS,
        'main': confirmed,
    })
    rec['ext_max'] = max([0] + [rec['buckets'].get('cuomo', {}).get('amt', 0),
                                rec['buckets'].get('ie', {}).get('total', 0),
                                rec['buckets'].get('aipac', {}).get('total', 0)])
    records.append(rec)

main_records = sorted([r for r in records if r['main']], key=lambda r: (-r['n_arenas'], -r['ext_max']))
demoted_records = sorted([r for r in records if not r['main']], key=lambda r: -r['ext_max'])
records = main_records                              # stats, topline & Schedule I use MAIN only
pac_agg = defaultdict(lambda: {'amt': 0.0, 'donors': 0, 'disp': ''})
for r in records:
    for p in r['buckets'].get('ie', {}).get('pacs', []):
        a = pac_agg[ckey(p['name'])]; a['amt'] += p['amt']; a['donors'] += 1
        if not a['disp']: a['disp'] = p['name']
pac_summary = sorted(({'name': v['disp'], 'amt': round(v['amt'], 2), 'donors': v['donors']}
                      for v in pac_agg.values()), key=lambda x: -x['amt'])

def _gave_ftc(r):
    return any('FIX THE CITY' in ckey(p['name']) for p in r['buckets'].get('ie', {}).get('pacs', []))
# Reynoso's *intake* from each network, net of any amount the campaign refunded.
# AIPAC uses the displayed records. The Cuomo / Fix the City total instead counts EVERY
# ZIP/employer-confirmed Reynoso -> Cuomo (campaign or his Fix the City super PAC) donor,
# read straight from subj so the total isn't narrowed by the card-display filters (small
# Cuomo-only gifts are dropped from the cards but still counted here). Name-only matches stay out.
_aipac_recs = [r for r in records if 'aipac' in r['buckets']]
def _net(r): return r['rey_amt'] - r['refund']   # gift to Reynoso, less anything refunded
def _net_k(k): return round(subj[k]['amt'], 2) - refund_by_key.get(k, 0.0)
def _cuomo_conf(k):
    sd = subj[k]
    if k in cuomo and (conf_of(sd['zip'], cuomo[k]['zip']) or emp_any(sd['emp'], cuomo[k]['emps'])):
        return True
    return (k in ie and any('FIX THE CITY' in ck for ck in ie[k]['pacs'])
            and (conf_of(sd['zip'], ie[k]['zip']) or emp_any(sd['emp'], ie[k]['emps'])))
_cuomo_keys = [k for k in subj if _cuomo_conf(k)]
_cuomo_shown = sum(1 for r in records if 'cuomo' in r['buckets'] or _gave_ftc(r))   # individually carded below

stats = {
    'subject': SUBJECT_COUNT,
    'listed': len(records),
    'footprint': sum(1 for r in records if r['n_arenas'] >= 1),
    'multi': sum(1 for r in records if r['n_arenas'] >= 2),
    'cuomo': sum(1 for r in records if 'cuomo' in r['buckets']),
    'ie': sum(1 for r in records if 'ie' in r['buckets']),
    'aipac': sum(1 for r in records if 'aipac' in r['buckets']),
    'refunded': sum(1 for r in records if r['refund']),
    'refund_offlist': len({(rr['last'], zd(rr['zip'])[:9]) for rr in refund_unmatched}),
    'demoted': len(demoted_records),
    'rey_from_cuomo': round(sum(_net_k(k) for k in _cuomo_keys), 2),
    'n_rey_from_cuomo': sum(1 for k in _cuomo_keys if _net_k(k) > 0.01),
    'rmv_cuomo_n': sum(1 for k in _cuomo_keys if _net_k(k) <= 0.01),
    'rmv_cuomo_amt': round(sum(refund_by_key.get(k, 0.0) for k in _cuomo_keys if _net_k(k) <= 0.01), 2),
    'cuomo_shown': _cuomo_shown,
    'rey_from_aipac': round(sum(_net(r) for r in _aipac_recs), 2),
    'n_rey_from_aipac': sum(1 for r in _aipac_recs if _net(r) > 0.01),
    'rmv_aipac_n': sum(1 for r in _aipac_recs if _net(r) <= 0.01),
    'rmv_aipac_amt': round(sum(r['refund'] for r in _aipac_recs if _net(r) <= 0.01), 2),
}
payload = json.dumps({'records': records,
                      'pac_summary': pac_summary, 'stats': stats, 'pac_refs': PAC_REFS})

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reynoso&rsquo;s Cuomo + AIPAC Donors</title>
<meta name="description" content="Which Reynoso for Congress donors also funded Andrew Cuomo, the conservative pro-Cuomo / anti-Zohran super PACs, and AIPAC &amp; allied PACs &mdash; a cross-reference of public campaign-finance filings.">
<style>
  :root{--ink:#1b1b1b;--paper:#f4f5f7;--card:#ffffff;--rule:#cdd1d8;--accent:#16294d;
    --muted:#646a75;--good:#2f5d3a;--warn:#8c600f;--chip:#eef0f4;--src:#5a5346;
    --cuo:#7a2540;--ie:#16294d;--aip:#1d3a6b;--ref:#8a1c1c}
  *{box-sizing:border-box}
  @media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
  body{margin:0;background:var(--paper);color:var(--ink);
    font-family:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;line-height:1.5;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1120px;margin:0 auto;padding:40px 24px 80px}
  header{border-bottom:3px double var(--ink);padding-bottom:18px;margin-bottom:24px}
  h1{font-size:33px;line-height:1.1;margin:0 0 10px;font-weight:700;letter-spacing:-.01em}
  .sub{color:var(--muted);font-size:15px;max-width:74ch;margin:0}
  .sub a{color:var(--accent);text-decoration:none;border-bottom:1px solid var(--rule)}
  .sub a:hover{background:var(--chip)}
  .topline{display:flex;flex-wrap:wrap;gap:0;margin:26px 0 0;border:1px solid var(--accent)}
  .topline .t{flex:1 1 240px;padding:18px 20px;background:var(--card);border-right:1px solid var(--rule)}
  .topline .t:last-child{border-right:0}
  .topline .t .n{font-family:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;font-size:30px;font-weight:700;display:block;letter-spacing:-.02em}
  .topline .t .l{font-size:12.5px;color:var(--muted);margin-top:5px;display:block}
  .topline .t .l b{color:var(--ink)}
  .topline .t .sub{display:block;font-size:11px;letter-spacing:.03em;color:var(--ref);margin-top:3px}
  .note{font-size:12.5px;color:var(--muted);margin:14px 0;scroll-margin-top:16px}
  .note b{color:var(--ink)}
  .controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:28px 0 14px}
  input[type=search]{flex:1 1 280px;padding:10px 12px;border:1px solid var(--rule);background:var(--card);font:inherit;font-size:15px}
  h2{font-size:13px;text-transform:uppercase;letter-spacing:.14em;color:var(--muted);
    border-bottom:1px solid var(--rule);padding-bottom:6px;margin:42px 0 16px}
  .card{border:1px solid var(--rule);background:var(--card);margin:0 0 13px;display:flex;flex-wrap:wrap}
  .who{flex:1 1 300px;padding:16px 20px;border-right:1px solid var(--rule)}
  .arenas{flex:2 1 460px;padding:16px 18px;display:flex;flex-wrap:wrap;gap:0}
  .arena{flex:1 1 180px;padding:6px 14px;border-left:1px solid var(--rule)}
  .arena:first-child{border-left:0}
  .card.noarenas .who{border-right:0;border-bottom:0}
  .arena .ah{font-size:10px;text-transform:uppercase;letter-spacing:.09em;margin:0 0 6px;font-weight:700}
  .arena.cuo .ah{color:var(--cuo)} .arena.ie .ah{color:var(--ie)} .arena.aip .ah{color:var(--aip)}
  .arena .tot{font-family:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;font-size:18px;font-weight:600}
  .pac{font-size:12.5px;padding:3px 0;border-bottom:1px dotted var(--rule);display:flex;justify-content:space-between;gap:8px}
  .pac:last-child{border-bottom:0}
  .pac .amt{font-family:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;white-space:nowrap}
  .pac .src{display:block;font-family:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;font-size:9.5px;letter-spacing:.03em;text-transform:uppercase;color:var(--src)}
  .pac a,#pacTable a{color:var(--accent);text-decoration:none;border-bottom:1px solid var(--accent)}
  .pac a:hover,#pacTable a:hover{background:var(--chip)}
  .yr{color:var(--muted);font-weight:400}
  .name{font-size:18px;font-weight:700;margin:0 0 2px}
  .meta{font-size:12.5px;color:var(--muted);margin:2px 0}
  .reyamt{font-family:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;font-size:14px;margin-top:9px}
  .reyamt b{font-size:17px}
  .badge{display:inline-block;font-family:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;font-size:9.5px;letter-spacing:.05em;
    text-transform:uppercase;padding:2px 6px;margin:2px 4px 2px 0;border:1px solid var(--rule);vertical-align:middle}
  .badge.ref{color:#fff;background:var(--ref);border-color:var(--ref)}
  table{width:100%;border-collapse:collapse;font-size:14px}
  th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--rule)}
  th{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);font-weight:600}
  td.num,th.num{text-align:right;font-family:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;font-variant-numeric:tabular-nums}
  footer{margin-top:46px;border-top:1px solid var(--rule);padding-top:16px;font-size:12px;color:var(--muted)}
  footer a{color:var(--accent);text-decoration:none;border-bottom:1px solid var(--rule)}
  footer a:hover{background:var(--chip)}
  a:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  #noresults{color:var(--muted);font-size:14px;padding:26px 2px}
  .hidden{display:none}
  @media (max-width:810px){.who{border-right:0;border-bottom:1px solid var(--rule)}.arena{border-left:0;border-top:1px solid var(--rule)}.arena:first-child{border-top:0}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Reynoso&rsquo;s Cuomo + AIPAC Donors</h1>
    <p class="sub">Reynoso for Congress donors who also show up in Andrew&nbsp;Cuomo&rsquo;s mayoral campaign,
    the conservative, pro-Cuomo&nbsp;/&nbsp;anti-Zohran independent-expenditure PACs, or AIPAC&nbsp;&amp;&nbsp;allied PACs
    &mdash; plus everyone the campaign refunded. See the <a href="#method">methodology</a> and
    <a href="#disclaimers">disclaimers</a>.</p>
  </header>

  <div class="topline" id="topline"></div>

  <div class="controls">
    <input type="search" id="q" aria-label="Filter donors by name, committee, or employer" placeholder="Filter by donor, committee, or employer&hellip;">
  </div>

  <div id="cards"></div>
  <p id="noresults" class="hidden">No donors match the current filters.</p>

  <h2>IE / PAC committees</h2>
  <table id="pacTable"><thead><tr><th>Committee</th><th class="num">Reynoso donors</th><th class="num">Total (deduped)</th></tr></thead><tbody></tbody></table>

  <div class="note" id="method">
    <b>Method.</b> Donors matched by normalized <b>last&nbsp;+&nbsp;first</b> name (organizations whole), then
    <b>confirmed by full ZIP code</b> (or employer); name-only matches are treated as different people and excluded,
    so every donor shown is ZIP-confirmed. NYC-CFB and NY-State report the same 2025 IE committees, so those are
    <b>de-duplicated by committee</b> (larger figure kept), not added. Cuomo and AIPAC are separate arenas.
    &ldquo;Refunded&rdquo; = money the campaign returned (Schedule&nbsp;20A), tied to a donor by full ZIP and gift date.
    The <b>Cuomo&nbsp;/&nbsp;Fix the City</b> total counts <b>every</b> ZIP/employer-confirmed Reynoso donor who also gave
    to Cuomo&rsquo;s campaign or his Fix the City super PAC, including small gifts &mdash; the cards above list only the
    larger, individually notable donors, so not every counted donor is shown.
    <span id="offlist"></span>
  </div>

  <div class="note" id="disclaimers">
    <b>Disclaimers.</b> An independent cross-reference of public filings &mdash; not an official report; verify against the
    linked sources before relying on it. Data retrieved June&nbsp;16,&nbsp;2026; contributions through June&nbsp;3,&nbsp;2026.
    <b>As of June&nbsp;4,&nbsp;2026, additional refunds and donations may have been made that aren&rsquo;t captured here.</b>
  </div>

  <footer>
    <b>Sources.</b>
    <a href="https://www.fec.gov/data/candidate/H6NY07164/" target="_blank" rel="noopener">Reynoso for Congress (FEC)</a> &mdash; receipts, disbursements &amp; refunds &middot;
    <a href="https://www.nyccfb.info/" target="_blank" rel="noopener">NYC Campaign Finance Board</a> &mdash; Cuomo + NYC IE PACs &middot;
    <a href="https://publicreporting.elections.ny.gov/IndependentContributions/IndependentContributions" target="_blank" rel="noopener">NY State Board of Elections</a> &mdash; NY State IE filings &middot;
    AIPAC &amp; allied PACs (FEC) &mdash;
    <a href="https://www.fec.gov/data/committee/C00797670/" target="_blank" rel="noopener">AIPAC PAC</a>,
    <a href="https://www.fec.gov/data/committee/C00799031/" target="_blank" rel="noopener">United Democracy Project</a>,
    <a href="https://www.fec.gov/data/committee/C00710848/" target="_blank" rel="noopener">DMFI PAC</a>,
    <a href="https://www.fec.gov/data/committee/C00247403/" target="_blank" rel="noopener">NORPAC</a>,
    <a href="https://www.fec.gov/data/committee/C00345132/" target="_blank" rel="noopener">RJC PAC</a>.
    <br>Generated by <b>build_report.py</b> &middot; <a href="https://github.com/ericthor/reynoso-cuomo-aipac" target="_blank" rel="noopener">source on GitHub</a>.
  </footer>
</div>

<script>
const DATA = __PAYLOAD__;
const money = n => '$' + Math.round(n).toLocaleString('en-US');
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
const REFS=DATA.pac_refs||{};
const pacName=name=>{const u=REFS[name];return u?`<a href="${esc(u)}" target="_blank" rel="noopener" title="Source">${esc(name)}</a>`:esc(name);};

const st=DATA.stats;
document.getElementById('topline').innerHTML=[
  ['var(--cuo)',money(st.rey_from_cuomo),'Raised by Reynoso from Cuomo / Fix the City donors',st.n_rey_from_cuomo,st.rmv_cuomo_n,st.rmv_cuomo_amt],
  ['var(--aip)',money(st.rey_from_aipac),'Raised by Reynoso from AIPAC &amp; allied donors',st.n_rey_from_aipac,st.rmv_aipac_n,st.rmv_aipac_amt],
].map(([c,n,l,k,rn,ra])=>`<div class="t"><span class="n" style="color:${c}">${n}</span><span class="l">${l} &middot; <b>${k}</b> donor${k===1?'':'s'}</span>${rn?`<span class="sub">minus ${rn} refunded donor${rn===1?'':'s'} removed (&minus;${money(ra)}) as of Jun&nbsp;4</span>`:''}</div>`).join('');

const yrp = p => p.years ? ` <span class="yr">(${esc(p.years)})</span>` : '';
function arenaHTML(r){
  let out='';
  const b=r.buckets;
  if(b.cuomo) out+=`<div class="arena cuo"><p class="ah">Cuomo (mayor)${yrp(b.cuomo)}</p><div class="tot">${money(b.cuomo.amt)}</div></div>`;
  if(b.ie){
    const rows=b.ie.pacs.map(p=>`<div class="pac"><span>${pacName(p.name)}${yrp(p)}<span class="src">${esc(p.src)}</span></span><span class="amt">${money(p.amt)}</span></div>`).join('');
    out+=`<div class="arena ie"><p class="ah">NYC / NY&nbsp;State IE PACs</p><div class="tot">${money(b.ie.total)}</div>${rows}</div>`;
  }
  if(b.aipac){
    const rows=b.aipac.pacs.map(p=>`<div class="pac"><span>${esc(p.name)}${yrp(p)}</span><span class="amt">${money(p.amt)}</span></div>`).join('');
    out+=`<div class="arena aip"><p class="ah">AIPAC &amp; allies</p><div class="tot">${money(b.aipac.total)}</div>${rows}</div>`;
  }
  return out;
}
function cardHTML(r){
  const empocc=[r.occ,r.emp].filter(Boolean).map(esc).join(' · ');
  const refb=r.refund?`<span class="badge ref">Reynoso refunded ${money(r.refund)}${r.refund_dates?` &middot; ${esc(r.refund_dates)}`:''}</span>`:'';
  const arenas=r.n_arenas?`<div class="arenas">${arenaHTML(r)}</div>`:'';
  return `<div class="card${r.n_arenas?'':' noarenas'}" data-text="${esc((r.display+' '+r.emp+' '+JSON.stringify(r.buckets)).toLowerCase())}">
    <div class="who">
      <p class="name">${esc(r.display)}</p>
      <p class="meta">${empocc||'—'}</p>
      <p class="meta">${esc(r.loc)}</p>
      <p class="reyamt">Reynoso: <b>${money(r.rey_amt)}</b>${r.rey_dates?` <span class="yr">${esc(r.rey_dates)}</span>`:''}</p>
      <div>${refb}</div>
    </div>
    ${arenas}
  </div>`;
}
if(st.refund_offlist){document.getElementById('offlist').innerHTML=
  `A further <b>${st.refund_offlist}</b> Schedule&nbsp;20A refund${st.refund_offlist>1?'s':''} went to donors not in this filing, so ${st.refund_offlist>1?'they are':'it is'} not shown above.`;}
document.getElementById('cards').innerHTML=DATA.records.map(cardHTML).join('');
document.querySelector('#pacTable tbody').innerHTML=DATA.pac_summary.map(p=>
  `<tr><td>${pacName(p.name)}</td><td class="num">${p.donors}</td><td class="num">${money(p.amt)}</td></tr>`).join('');

const q=document.getElementById('q');
function apply(){
  const t=q.value.trim().toLowerCase();
  let shown=0;
  document.querySelectorAll('.card').forEach(c=>{
    const ok=(!t||c.dataset.text.includes(t));
    c.classList.toggle('hidden',!ok);
    if(ok)shown++;
  });
  document.getElementById('noresults').classList.toggle('hidden',shown>0);
}
q.addEventListener('input',apply);
</script>
</body>
</html>"""

# Output goes in public/ — the ONLY directory Netlify publishes, so the source data,
# build script, and README are never uploaded to the live site.
os.makedirs('public', exist_ok=True)
with open('public/index.html', 'w') as f:
    f.write(TEMPLATE.replace('__PAYLOAD__', payload))

print(f"Wrote public/index.html | {stats['subject']} donors, "
      f"{stats['footprint']} with outside footprint ({stats['multi']} in 2+ arenas) | "
      f"Cuomo {stats['cuomo']}, IE {stats['ie']}, AIPAC {stats['aipac']}, refunded {stats['refunded']} "
      f"(+{stats['refund_offlist']} off-filing)")
