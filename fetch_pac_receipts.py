#!/usr/bin/env python3
"""Pull 2025-26 itemized receipts (who donated TO the PAC) for AIPAC and allied
committees from the FEC API into one CSV matching the existing AIPAC schema.

Resumable: progress is checkpointed per committee, so re-running continues where
it stopped (e.g. after a rate-limit). Smallest committees are fetched first.

Usage:
    export FEC_API_KEY=...        # free key from https://api.data.gov/signup/ (1,000/hr)
    python3 fetch_pac_receipts.py # without a key it uses DEMO_KEY (~30/hr, won't finish AIPAC)
"""
import os, csv, json, time, urllib.request, urllib.parse, urllib.error

API_KEY = os.environ.get('FEC_API_KEY', 'DEMO_KEY')
PERIOD = 2026                                   # FEC two-year period covering 2025-2026
OUTDIR = 'data/aipac-2026'
CHECKPOINT = os.path.join(OUTDIR, '.checkpoint.json')
COMBINED = os.path.join(OUTDIR, 'AIPAC & Allies 2025-2026 - receipts.csv')

# committee_id -> committee_name (names match the 2023-24 file so it's a drop-in)
COMMITTEES = [
    ('C00799031', "UNITED DEMOCRACY PROJECT ('UDP')"),
    ('C00710848', 'DMFI PAC'),
    ('C00345132', 'REPUBLICAN JEWISH COALITION-POLITICAL ACTION COMMITTEE (RJC-PAC)'),
    ('C00247403', 'NORPAC'),
    ('C00797670', 'AMERICAN ISRAEL PUBLIC AFFAIRS COMMITTEE POLITICAL ACTION COMMITTEE'),
]
COLUMNS = ['committee_id', 'committee_name', 'report_year', 'entity_type', 'entity_type_desc',
           'contributor_prefix', 'contributor_name', 'contributor_first_name', 'contributor_middle_name',
           'contributor_last_name', 'contributor_suffix', 'contributor_street_1', 'contributor_street_2',
           'contributor_city', 'contributor_state', 'contributor_zip', 'contributor_employer',
           'contributor_occupation', 'contributor_id', 'receipt_type', 'receipt_type_desc',
           'receipt_type_full', 'contribution_receipt_amount', 'contribution_receipt_date',
           'two_year_transaction_period']

os.makedirs(OUTDIR, exist_ok=True)

def load_ckpt():
    try:
        with open(CHECKPOINT) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_ckpt(ck):
    with open(CHECKPOINT, 'w') as f:
        json.dump(ck, f, indent=2)

def api_get(params, tries=6):
    qs = urllib.parse.urlencode(params)
    url = f'https://api.open.fec.gov/v1/schedules/schedule_a/?{qs}'
    delay = 3
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):            # rate-limited / temporarily unavailable
                if attempt == tries - 1:
                    raise RuntimeError('RATE_LIMIT')
                time.sleep(delay); delay = min(delay * 2, 60); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
            time.sleep(delay); delay = min(delay * 2, 60)
    raise RuntimeError('RATE_LIMIT')

def row_of(r, cid, cname):
    g = r.get
    return {
        'committee_id': cid, 'committee_name': cname,
        'report_year': g('report_year'), 'entity_type': g('entity_type'),
        'entity_type_desc': g('entity_type_desc'), 'contributor_prefix': g('contributor_prefix'),
        'contributor_name': g('contributor_name'), 'contributor_first_name': g('contributor_first_name'),
        'contributor_middle_name': g('contributor_middle_name'), 'contributor_last_name': g('contributor_last_name'),
        'contributor_suffix': g('contributor_suffix'), 'contributor_street_1': g('contributor_street_1'),
        'contributor_street_2': g('contributor_street_2'), 'contributor_city': g('contributor_city'),
        'contributor_state': g('contributor_state'), 'contributor_zip': g('contributor_zip'),
        'contributor_employer': g('contributor_employer'), 'contributor_occupation': g('contributor_occupation'),
        'contributor_id': g('contributor_id'), 'receipt_type': g('receipt_type'),
        'receipt_type_desc': g('receipt_type_desc'), 'receipt_type_full': g('receipt_type_full'),
        'contribution_receipt_amount': g('contribution_receipt_amount'),
        'contribution_receipt_date': g('contribution_receipt_date'),
        'two_year_transaction_period': g('two_year_transaction_period'),
    }

def fetch_committee(cid, cname, ck):
    state = ck.get(cid, {})
    if state.get('done'):
        print(f'  {cid} {cname[:28]:28} already complete ({state.get("rows", "?")} rows)')
        return True
    path = os.path.join(OUTDIR, f'{cid}.csv')
    fresh = not state                            # first time for this committee
    f = open(path, 'a', newline='')
    w = csv.DictWriter(f, fieldnames=COLUMNS)
    if fresh and os.path.getsize(path) == 0:
        w.writeheader()
    rows = state.get('rows', 0)
    params = {'committee_id': cid, 'two_year_transaction_period': PERIOD,
              'per_page': 100, 'sort': 'contribution_receipt_date', 'api_key': API_KEY}
    if state.get('last_index'):
        params['last_index'] = state['last_index']
        params['last_contribution_receipt_date'] = state['last_date']
    try:
        while True:
            data = api_get(params)
            results = data.get('results', [])
            if not results:
                break
            for r in results:
                w.writerow(row_of(r, cid, cname))
            rows += len(results)
            f.flush()
            li = data.get('pagination', {}).get('last_indexes') or {}
            total = data.get('pagination', {}).get('count', 0)
            ck[cid] = {'last_index': li.get('last_index'), 'last_date': li.get('last_contribution_receipt_date'),
                       'rows': rows, 'done': False}
            save_ckpt(ck)
            print(f'  {cid} {cname[:24]:24} {rows:>6}/{total} rows', end='\r')
            if not li.get('last_index') or len(results) < 100:
                break
            params['last_index'] = li['last_index']
            params['last_contribution_receipt_date'] = li['last_contribution_receipt_date']
            time.sleep(0.3)
    finally:
        f.close()
    ck[cid]['done'] = True
    save_ckpt(ck)
    print(f'  {cid} {cname[:24]:24} {rows:>6} rows  DONE          ')
    return True

def combine(ck):
    done = [cid for cid, _ in COMMITTEES if ck.get(cid, {}).get('done')]
    with open(COMBINED, 'w', newline='') as out:
        w = csv.DictWriter(out, fieldnames=COLUMNS); w.writeheader()
        total = 0
        for cid in [c for c, _ in COMMITTEES if c in done]:
            with open(os.path.join(OUTDIR, f'{cid}.csv')) as f:
                for row in csv.DictReader(f):
                    w.writerow(row); total += 1
    return total, done

def main():
    print(f'FEC key: {"DEMO_KEY (rate-limited)" if API_KEY == "DEMO_KEY" else "custom key"} | period {PERIOD}')
    ck = load_ckpt()
    rate_limited = False
    for cid, cname in COMMITTEES:
        try:
            fetch_committee(cid, cname, ck)
        except RuntimeError as e:
            if str(e) == 'RATE_LIMIT':
                print(f'\n  RATE LIMIT hit on {cid} ({cname[:24]}). Progress saved — re-run to resume '
                      f'(set FEC_API_KEY for a 1,000/hr key).')
                rate_limited = True
                break
            raise
    n_done = sum(1 for cid, _ in COMMITTEES if ck.get(cid, {}).get('done'))
    if n_done:
        total, done = combine(ck)
        print(f'\nWrote {COMBINED}: {total:,} rows from {len(done)}/{len(COMMITTEES)} committees.')
    print('All committees complete.' if not rate_limited and n_done == len(COMMITTEES)
          else 'Incomplete — re-run to continue.')

if __name__ == '__main__':
    main()
