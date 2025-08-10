# app.py — PI Finder using ClinicalTrials.gov API v2 only
# Pulls PIs from contactsLocationsModule.overallOfficials (no classic API)

import io, csv, re, time
import requests
from flask import Flask, request, render_template_string, Response

API_V2_STUDIES = "https://clinicaltrials.gov/api/v2/studies"
HEADERS = {
    "User-Agent": "PI-Finder/1.0 (+research contact: you@example.com)",
    "Accept": "application/json",
}

# Treat these as investigator roles (adjust if you want fewer/more)
ROLE_RX = re.compile(
    r"(principal\s*investigator|site\s*principal\s*investigator|study\s*chair|study\s*director|sub-?investigator)",
    re.I,
)

app = Flask(__name__)

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
  .small{font-size:12px}
</style>
</head>
<body>
  <header>
    <h1>PI Finder · ClinicalTrials.gov</h1>
    <div class="sub">Uses the modern API v2 only — pulls Overall Officials (PIs) directly.</div>
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
          <input class="input" type="number" name="max" value="{{max or 100}}">
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

      {% if error %}
        <div class="mt8" style="color:#b91c1c">Error: {{error}}</div>
      {% elif not tried %}
        <div class="muted mt8">Enter a city and click Search.</div>
      {% elif rows|length == 0 %}
        <div class="muted mt8">No PI names were returned for matched trials. Try removing Condition/Phase or increasing Max.</div>
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
      <div class="mt8 small muted">
        Endpoint used: <code>{{v2_url}}</code>
      </div>
    </div>
  </div>
</body>
</html>
"""

def v2_list(expr: str, page_size: int = 200):
    """Get a list of studies using API v2 (single page)."""
    params = {
        "query.term": expr,
        "pageSize": str(page_size),
        "format": "json",
        "countTotal": "true",
    }
    url = f"{API_V2_STUDIES}?query.term={requests.utils.quote(expr)}&pageSize={page_size}&format=json&countTotal=true"
    r = requests.get(API_V2_STUDIES, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    studies = data.get("studies", []) if isinstance(data, dict) else []
    return studies, url

def match_city_state(study: dict, city: str, state: str):
    proto = study.get("protocolSection", {}) or {}
    mod = proto.get("contactsLocationsModule", {}) or {}
    locs = mod.get("locations", []) or []
    want_city = (city or "").strip().lower()
    want_state = (state or "").strip().lower()
    for loc in locs:
        c = (loc.get("city") or "")
        s = (loc.get("state") or "")
        fac = (loc.get("facility") or "")
        city_ok = (not want_city) or (want_city in c.lower()) or (want_city in (fac or "").lower())
        state_ok = (not want_state) or (want_state in (s or "").lower())
        if city_ok and state_ok:
            return c, s
    return None, None

def extract_officials_v2(study: dict):
    """Pull overallOfficials from v2 contactsLocationsModule."""
    proto = study.get("protocolSection", {}) or {}
    mod = proto.get("contactsLocationsModule", {}) or {}
    offs = mod.get("overallOfficials", []) or []

    out = []
    for off in offs:
        # v2 typically uses these keys:
        name = off.get("name") or ""
        role = off.get("role") or ""
        aff  = off.get("affiliation") or ""
        if name and role and ROLE_RX.search(role):
            out.append({"name": name, "role": role, "affiliation": aff})
    return out

def title_status_phase_v2(study: dict):
    proto = study.get("protocolSection", {}) or {}
    idm = proto.get("identificationModule", {}) or {}
    title = idm.get("officialTitle") or idm.get("briefTitle") or ""
    status = (proto.get("statusModule", {}) or {}).get("overallStatus") or ""
    phases = proto.get("designModule", {}).get("phases") or []
    phases_text = ";".join(phases) if isinstance(phases, list) else (phases or "")
    nct = idm.get("nctId") or study.get("nctId") or ""
    return title, status, phases_text, nct

def build_rows_v2(studies, user_city, user_state, max_rows):
    rows = []
    matched = 0
    for s in studies:
        c, s_state = match_city_state(s, user_city, user_state)
        if c is None:
            continue
        matched += 1
        officials = extract_officials_v2(s)
        if not officials:
            continue
        title, status, phases, nct = title_status_phase_v2(s)
        for off in officials:
            rows.append({
                "pi_name": off["name"], "role": off["role"], "affiliation": off.get("affiliation",""),
                "city": c, "state": s_state, "nct_id": nct, "status": status, "phases": phases,
                "study_title": title, "source": "v2.contactsLocationsModule.overallOfficials"
            })
        if len(rows) >= max_rows:
            break

    # Deduplicate by (name, city, state)
    seen = set(); deduped = []
    for r in rows:
        key = (r["pi_name"].lower(), (r["city"] or "").lower(), (r["state"] or "").lower())
        if key in seen: continue
        seen.add(key); deduped.append(r)
    return matched, deduped

@app.route("/")
def home():
    city = request.args.get("city","")
    tried = bool(city)
    state = request.args.get("state","")
    condition = request.args.get("condition","")
    phase = request.args.get("phase","any")
    max_trials = int(request.args.get("max","100") or "100")

    error = ""
    rows = []
    fetched = matched = 0
    v2_url = ""

    if tried:
        try:
            terms = " ".join([t for t in [city, state, condition, (phase if phase and phase.lower() != "any" else "")] if t]).strip() or city
            studies_v2, v2_url = v2_list(terms, page_size=min(max_trials, 200))
            fetched = len(studies_v2)
            matched, rows = build_rows_v2(studies_v2, city, state, max_trials)
        except Exception as e:
            error = str(e)

    export_url = f"/export?city={city}&state={state}&condition={condition}&phase={phase}&max={max_trials}"
    return render_template_string(PAGE, city=city, state=state, condition=condition, phase=phase, max=max_trials,
                                  tried=tried, rows=rows, fetched=fetched, matched=matched, error=error, v2_url=v2_url)

@app.route("/export")
def export():
    city = request.args.get("city","")
    state = request.args.get("state","")
    condition = request.args.get("condition","")
    phase = request.args.get("phase","any")
    max_trials = int(request.args.get("max","100") or "100")

    terms = " ".join([t for t in [city, state, condition, (phase if phase and phase.lower() != "any" else "")] if t]).strip() or city
    studies_v2, _ = v2_list(terms, page_size=min(max_trials, 200))
    matched, rows = build_rows_v2(studies_v2, city, state, max_trials)

    def generate():
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["pi_name","role","affiliation","city","state","nct_id","status","phases","study_title","source"])
        writer.writeheader()
        yield output.getvalue(); output.seek(0); output.truncate(0)
        for r in rows:
            writer.writerow(r)
            yield output.getvalue(); output.seek(0); output.truncate(0)

    filename = f"pi_{city.replace(' ','_').lower()}_{(state or 'all').lower()}.csv"
    return Response(generate(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})

if __name__ == "__main__":
    # Local dev
    app.run(host="0.0.0.0", port=5000, debug=True)
