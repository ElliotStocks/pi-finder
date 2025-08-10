# app.py — PI Finder using ClinicalTrials.gov Full Studies v1 (single endpoint)
import io, csv, re, math
import requests
from flask import Flask, request, render_template_string, Response

API_V1_FULL_STUDIES = "https://clinicaltrials.gov/api/query/full_studies"
HEADERS = {"User-Agent": "PI-Finder/1.0 (+contact: research use)"}
ROLE_RX = re.compile(r"(principal\s*investigator|study\s*chair|study\s*director|sub-?investigator)", re.I)

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
  .card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px;box-shadow:0 1px 2px rgba(0,0,0,0.03)}
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
    <div class="sub">Search by city. Uses the Full Studies API (v1) which contains PI names.</div>
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
          <input class="input" type="number" name="max" value="{{max or 200}}">
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
    </div>
  </div>
</body>
</html>
"""

def fetch_full_studies(expr, max_rnk):
    """Pull Full Studies (v1) in pages. Returns list of Study dicts."""
    page_size = 100  # v1 is happy with 100/page
    studies = []
    total = 0
    for start in range(1, max_rnk + 1, page_size):
        end = min(start + page_size - 1, max_rnk)
        params = {
            "expr": expr,
            "min_rnk": start,
            "max_rnk": end,
            "fmt": "json"
        }
        r = requests.get(API_V1_FULL_STUDIES, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        resp = data.get("FullStudiesResponse", {})
        total = max(total, resp.get("NStudiesFound", 0))
        chunk = resp.get("FullStudies", []) or []
        # Each item: {"Study": {...}}
        for item in chunk:
            if "Study" in item:
                studies.append(item["Study"])
        # Stop early if we’ve reached the end
        if end >= total or not chunk:
            break
    return studies, total

def pick_text(v):
    if isinstance(v, list):
        return "; ".join([x for x in v if x])
    return v or ""

def city_state_match(proto, city, state):
    """Return first (city,state) facility match in ContactsLocationsModule."""
    mod = proto.get("ProtocolSection", {}).get("ContactsLocationsModule", {})
    locs = mod.get("LocationList", {}).get("Location", []) or []
    city_norm = (city or "").strip().lower()
    state_norm = (state or "").strip().lower()
    for loc in locs:
        c = (loc.get("LocationCity") or "").lower()
        s = (loc.get("LocationState") or "").lower()
        fac = (loc.get("LocationFacility") or "").lower()
        city_ok = (not city_norm) or (city_norm in c) or (city_norm in fac)
        state_ok = (not state_norm) or (state_norm in s)
        if city_ok and state_ok:
            return (loc.get("LocationCity") or ""), (loc.get("LocationState") or "")
    return None, None

def extract_officials(proto):
    """Return list of overall officials with roles."""
    mod = proto.get("ProtocolSection", {}).get("ContactsLocationsModule", {})
    offs = mod.get("OverallOfficialList", {}).get("OverallOfficial", [])  # primary structure
    # Some records use a slightly different key:
    if not offs:
        offs = mod.get("OverallOfficials", [])  # fallback if present
    out = []
    for off in offs or []:
        name = off.get("OverallOfficialName") or off.get("OfficialName") or ""
        role = off.get("OverallOfficialRole") or off.get("OfficialRole") or ""
        aff  = off.get("OverallOfficialAffiliation") or off.get("OfficialAffiliation") or ""
        if name and role and ROLE_RX.search(role):
            out.append({"name": name, "role": role, "affiliation": aff})
    return out

def build_rows(studies, city, state):
    rows = []
    matched = 0
    for s in studies:
        proto = s.get("ProtocolSection", {}) or {}
        idm = proto.get("IdentificationModule", {}) or {}
        nct = idm.get("NCTId") or ""
        title = idm.get("OfficialTitle") or idm.get("BriefTitle") or ""
        status = proto.get("StatusModule", {}).get("OverallStatus") or ""
        phases_list = proto.get("DesignModule", {}).get("PhaseList", {}).get("Phase", [])
        phases = ";".join(phases_list) if isinstance(phases_list, list) else (phases_list or "")

        c, s_abbrev = city_state_match(s, city, state)
        if c is None:
            continue
        matched += 1

        officials = extract_officials(s)
        for off in officials:
            rows.append({
                "pi_name": off["name"],
                "role": off["role"],
                "affiliation": off.get("affiliation",""),
                "city": c,
                "state": s_abbrev,
                "nct_id": nct,
                "status": status,
                "phases": phases,
                "study_title": title,
                "source": "v1.full_studies.overall_officials"
            })

    # Dedupe by (name, city, state)
    seen = set()
    deduped = []
    for r in rows:
        key = (r["pi_name"].lower(), (r["city"] or "").lower(), (r["state"] or "").lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return matched, deduped

@app.route("/")
def home():
    city = request.args.get("city","")
    tried = bool(city)
    state = request.args.get("state","")
    condition = request.args.get("condition","")
    phase = request.args.get("phase","any")
    max_trials = int(request.args.get("max","200") or "200")

    error = ""
    rows = []
    fetched = matched = 0

    if tried:
        try:
            # Build expression for v1 search (city + state + optional condition/phase)
            expr_parts = [city, state, condition, (phase if phase and phase.lower() != "any" else "")]
            expr = " ".join([p for p in expr_parts if p]).strip() or city
            studies, total = fetch_full_studies(expr, max_trials)
            fetched = min(total, max_trials)
            matched, rows = build_rows(studies, city, state)
        except Exception as e:
            error = str(e)

    export_url = f"/export?city={city}&state={state}&condition={condition}&phase={phase}&max={max_trials}"
    return render_template_string(PAGE, city=city, state=state, condition=condition, phase=phase, max=max_trials,
                                  tried=tried, rows=rows, fetched=fetched, matched=matched, error=error,
                                  export_url=export_url)

@app.route("/export")
def export():
    city = request.args.get("city","")
    state = request.args.get("state","")
    condition = request.args.get("condition","")
    phase = request.args.get("phase","any")
    max_trials = int(request.args.get("max","200") or "200")

    expr_parts = [city, state, condition, (phase if phase and phase.lower() != "any" else "")]
    expr = " ".join([p for p in expr_parts if p]).strip() or city
    studies, total = fetch_full_studies(expr, max_trials)
    matched, rows = build_rows(studies, city, state)

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
