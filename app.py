# app.py — PI Finder (Render-ready)
import re, time, io, csv
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string, Response

API_BASE = "https://clinicaltrials.gov/api/v2"
HEADERS = {"User-Agent": "PI-Finder/1.0 (+contact: research use)"}
ROLE_RX = re.compile(r"(principal\s*investigator|site\s*principal\s*investigator|study\s*chair|study\s*director|sub-?investigator)", re.I)

PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PI Finder · ClinicalTrials.gov</title>
<style>
  :root{--bg:#f7f7f8;--card:#fff;--border:#e5e7eb;--muted:#6b7280}
  *{box-sizing:border-box} body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;background:var(--bg);color:#111827}
  header{max-width:1000px;margin:24px auto 0;padding:0 16px}
  h1{font-size:22px;margin:0 0 8px}.sub{color:var(--muted);font-size:13px}
  .wrap{max-width:1000px;margin:16px auto 32px;padding:0 16px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px;box-shadow:0 1px 2px rgba(0,0,0,.03)}
  label{display:block;font-size:13px;margin-bottom:6px} input,select,button{font:inherit}
  .input,.select{width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:#fff}
  .grid{display:grid;gap:12px} @media (min-width:900px){.grid-6{grid-template-columns:repeat(6,1fr)}}
  .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
  .btn{padding:10px 14px;border:1px solid var(--border);border-radius:10px;background:#111827;color:#fff;cursor:pointer;text-decoration:none}
  table{width:100%;border-collapse:collapse} th,td{border-bottom:1px solid var(--border);padding:8px;text-align:left;vertical-align:top;font-size:14px}
  .muted{color:var(--muted)} .pill{display:inline-block;padding:2px 8px;border-radius:9999px;border:1px solid var(--border);font-size:12px;background:#fafbff}
  .mt8{margin-top:8px}.mt12{margin-top:12px}
</style>
</head>
<body>
  <header>
    <h1>PI Finder · ClinicalTrials.gov</h1>
    <div class="sub">Search by city. This reads public trial pages to extract PI names.</div>
  </header>
  <div class="wrap">
    <div class="card">
      <form method="GET" action="/" class="grid grid-6">
        <div style="grid-column: span 2;">
          <label>City</label>
          <input class="input" name="city" value="{{city or ''}}" placeholder="e.g., San Diego" required>
        </div>
        <div>
          <label>State/Region</label>
          <input class="input" name="state" value="{{state or ''}}" placeholder="e.g., CA">
        </div>
        <div>
          <label>Condition (optional)</label>
          <input class="input" name="condition" value="{{condition or ''}}" placeholder="e.g., oncology">
        </div>
        <div>
          <label>Phase (optional)</label>
          <select class="select" name="phase">
            {% set phases = ['any','phase 1','phase 2','phase 3','phase 4'] %}
            {% for p in phases %}
              <option value="{{p}}" {% if phase==p %}selected{% endif %}>{{p.title() if p!='any' else 'Any'}}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label>Max trials to scan</label>
          <input class="input" type="number" name="max" value="{{max or 400}}">
        </div>
        <div class="row" style="align-self:end">
          <button class="btn" type="submit">Search</button>
          {% if rows %}
            <a class="btn" style="background:#fff;color:#111827" href="{{export_url}}">Export CSV</a>
          {% endif %}
        </div>
      </form>
    </div>

    <div class="card mt12">
      <div class="row" style="gap:12px;">
        <strong>Results</strong>
        <span class="pill">{{rows|length}}</span>
        <span class="muted">Fetched: {{fetched}} · City-matched: {{matched}} · With PI names: {{rows|length}}</span>
      </div>

      {% if not tried %}
        <div class="muted mt8">Enter a city and click Search.</div>
      {% elif rows|length == 0 %}
        <div class="muted mt8">No PI names were published in matched trials. Try removing Condition/Phase or using a nearby city.</div>
      {% else %}
        <div class="mt8" style="max-height:60vh;overflow:auto;border:1px solid var(--border);border-radius:12px;">
          <table>
            <thead><tr>
              <th>PI Name</th><th>Role</th><th>Affiliation</th><th>City/State</th><th>Status / Phase</th><th>Study Title</th><th>NCT</th><th>Source</th>
            </tr></thead>
            <tbody>
              {% for r in rows %}
                <tr>
                  <td><strong>{{r['pi_name']}}</strong></td>
                  <td>{{r['role']}}</td>
                  <td>{{r['affiliation']}}</td>
                  <td>{{r['city']}}{{', ' + r['state'] if r['state'] else ''}}</td>
                  <td>{{r['status']}}{{' / ' + r['phases'] if r['phases'] else ''}}</td>
                  <td>{{r['study_title']}}</td>
                  <td><a href="https://clinicaltrials.gov/study/{{r['nct_id']}}" target="_blank" rel="noreferrer">{{r['nct_id']}}</a></td>
                  <td>{{r['source']}}</td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      {% endif %}
    </div>
  </div>
</body>
</html>
"""

app = Flask(__name__)

def fetch_studies(term, page_size=800):
    params = {"query.term": term, "pageSize": str(page_size), "format": "json", "countTotal": "true"}
    r = requests.get(f"{API_BASE}/studies", params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("studies", []) if isinstance(data, dict) else []

def city_state_match(study, city, state):
    city_norm = (city or "").strip().toLowerCase() if hasattr(str, "toLowerCase") else (city or "").strip().lower()
    state_norm = (state or "").strip().lower()
    locs = []
    locations = study.get("protocolSection", {}).get("contactsLocationsModule", {}).get("locations", []) or study.get("locations", [])
    for loc in locations or []:
        c = (loc.get("city") or "").lower()
        s = (loc.get("state") or "").lower()
        fac = (loc.get("facility") or "").lower()
        city_ok = (not city_norm) or (city_norm in c) or (city_norm in fac)
        state_ok = (not state_norm) or (state_norm in s)
        if city_ok and state_ok:
            locs.append(loc)
    return locs

def extract_overall_status(study):
    return study.get("protocolSection", {}).get("statusModule", {}).get("overallStatus") or study.get("overallStatus") or ""

def extract_phases(study):
    phases = study.get("protocolSection", {}).get("designModule", {}).get("phases") or study.get("phases") or []
    return ";".join(phases) if isinstance(phases, list) else (phases or "")

def extract_title(study):
    idm = study.get("protocolSection", {}).get("identificationModule", {}) or {}
    return idm.get("officialTitle") or idm.get("briefTitle") or study.get("briefTitle") or ""

def extract_nct_id(study):
    idm = study.get("protocolSection", {}).get("identificationModule", {}) or {}
    return idm.get("nctId") or study.get("nctId") or ""

def fetch_study_html(nct_id):
    r = requests.get(f"https://clinicaltrials.gov/study/{nct_id}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text

def parse_pi_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []

    # 1) Overall Official blocks
    for hdr in soup.find_all(string=re.compile(r"Overall\s+Official", re.I)):
        container = hdr.find_parent()
        if not container:
            continue
        text = container.get_text(" ", strip=True)
        # Pattern A: explicit labels
        for m in re.finditer(r"Name:\s*(?P<name>[^:]+?)\s+Role:\s*(?P<role>[^:]+?)\s+(?:Affiliation:\s*(?P<aff>[^:]+?))?(?:\s{2,}|\Z)", text, flags=re.I):
            role = (m.group("role") or "").strip()
            if ROLE_RX.search(role):
                out.append({"name": m.group("name").strip(), "role": role, "affiliation": (m.group("aff") or "").strip()})
        # Pattern B: nearby role hit + name-like text
        for role_hit in re.finditer(ROLE_RX, text):
            window = text[max(role_hit.start()-120,0):role_hit.end()+120]
            mname = re.search(r"([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){0,3})(?:,\s*(?:MD|PhD|DO|MBBS|MBChB))?", window)
            if mname:
                out.append({"name": mname.group(1).strip(), "role": role_hit.group(0), "affiliation": ""})

    # 2) Site-level investigators under Contacts & Locations
    contacts_hdr = soup.find(string=re.compile(r"Contacts\s+and\s+Locations", re.I))
    if contacts_hdr:
        region = contacts_hdr.find_parent()
        if region:
            for el in region.find_all(True):
                t = el.get_text(" ", strip=True)
                mrole = ROLE_RX.search(t)
                if not mrole:
                    continue
                mname = re.search(r"Name:\s*([^|]+?)(?:\s{2,}|\sRole:|\Z)", t, flags=re.I)
                if mname:
                    name = mname.group(1).strip()
                else:
                    window = t[max(mrole.start()-120,0):mrole.end()+120]
                    mname2 = re.search(r"([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){0,3})(?:,\s*(?:MD|PhD|DO|MBBS|MBChB))?", window)
                    name = mname2.group(1).strip() if mname2 else ""
                maff = re.search(r"Affiliation:\s*([^|]+?)(?:\s{2,}|\Z)", t, flags=re.I)
                aff = maff.group(1).strip() if maff else ""
                if name:
                    out.append({"name": name, "role": mrole.group(0), "affiliation": aff})

    # 3) Last resort sweep
    page_text = soup.get_text(" ", strip=True)
    for role_hit in re.finditer(ROLE_RX, page_text):
        window = page_text[max(role_hit.start()-120,0):role_hit.end()+120]
        mname = re.search(r"([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+){0,3})(?:,\s*(?:MD|PhD|DO|MBBS|MBChB))?", window)
        if mname:
            out.append({"name": mname.group(1).strip(), "role": role_hit.group(0), "affiliation": ""})

    # Dedupe
    seen, deduped = set(), []
    for r in out:
        key = (r["name"].lower(), r["role"].lower())
        if key in seen: continue
        seen.add(key); deduped.append(r)
    return deduped

def search(city, state, condition="", phase="any", max_trials=400, delay=0.4):
    term = " ".join([x for x in [city, state, condition, "" if phase=="any" else phase] if x]).strip()
    studies = fetch_studies(term, page_size=min(max_trials, 1000))
    matched = []
    for s in studies:
        # lower() to compare
        city_norm = (city or "").strip().lower()
        state_norm = (state or "").strip().lower()
        locs = []
        locations = s.get("protocolSection", {}).get("contactsLocationsModule", {}).get("locations", []) or s.get("locations", [])
        for loc in locations or []:
            c = (loc.get("city") or "").lower()
            s2 = (loc.get("state") or "").lower()
            fac = (loc.get("facility") or "").lower()
            city_ok = (not city_norm) or (city_norm in c) or (city_norm in fac)
            state_ok = (not state_norm) or (state_norm in s2)
            if city_ok and state_ok:
                locs.append(loc)
        if locs: matched.append((s, locs))

    rows = []
    for s, locs in matched[:max_trials]:
        nct = extract_nct_id(s); title = extract_title(s)
        status = extract_overall_status(s); phases = extract_phases(s)
        try:
            html = fetch_study_html(nct)
        except Exception:
            continue
        invs = parse_pi_from_html(html)
        if invs:
            loc = locs[0]
            for inv in invs:
                rows.append({
                    "pi_name": inv["name"], "role": inv["role"], "affiliation": inv.get("affiliation",""),
                    "city": loc.get("city",""), "state": loc.get("state",""),
                    "nct_id": nct, "status": status, "phases": phases, "study_title": title, "source": "html"
                })
        time.sleep(delay)
    # Dedupe
    seen, deduped = set(), []
    for r in rows:
        key = (r["pi_name"].lower(), (r["city"] or "").lower(), (r["state"] or "").lower())
        if key in seen: continue
        seen.add(key); deduped.append(r)
    return studies, matched, deduped

app = Flask(__name__)

@app.route("/")
def home():
    city = request.args.get("city","")
    tried = bool(city)
    state = request.args.get("state","")
    condition = request.args.get("condition","")
    phase = request.args.get("phase","any")
    max_trials = int(request.args.get("max","400") or "400")

    rows = []; fetched = matched = 0
    if tried:
        studies, matched_pairs, rows = search(city, state, condition, phase, max_trials=max_trials)
        fetched = len(studies); matched = len(matched_pairs)

    export_url = f"/export?city={city}&state={state}&condition={condition}&phase={phase}&max={max_trials}"
    return render_template_string(PAGE, city=city, state=state, condition=condition, phase=phase, max=max_trials,
                                  rows=rows, fetched=fetched, matched=matched, tried=tried, export_url=export_url)

@app.route("/export")
def export():
    city = request.args.get("city","")
    state = request.args.get("state","")
    condition = request.args.get("condition","")
    phase = request.args.get("phase","any")
    max_trials = int(request.args.get("max","400") or "400")
    _, _, rows = search(city, state, condition, phase, max_trials=max_trials)

    def generate():
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["pi_name","role","affiliation","city","state","nct_id","status","phases","study_title","source"])
        writer.writeheader()
        yield output.getvalue(); output.seek(0); output.truncate(0)
        for r in rows:
            writer.writerow(r)
            yield output.getvalue(); output.seek(0); output.truncate(0)

    filename = f"pi_{city.replace(' ','_').lower()}_{state.lower() or 'all'}.csv"
    return Response(generate(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})

# Render runs via: gunicorn app:app --bind 0.0.0.0:$PORT
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
