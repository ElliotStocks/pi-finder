# app.py — PI Finder (v2 list + classic v1 details, with on-page diagnostics)

import io, csv, re, time
import requests
from flask import Flask, request, render_template_string, Response

# Endpoints
API_V2_STUDIES = "https://clinicaltrials.gov/api/v2/studies"
API_V1_FULL = "https://classic.clinicaltrials.gov/api/query/full_studies"

HEADERS = {
    "User-Agent": "PI-Finder/1.0 (+contact: research use; email: you@example.com)",
    "Accept": "application/json",
}

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
  .err{color:#b91c1c}
  .ok{color:#065f46}
</style>
</head>
<body>
  <header>
    <h1>PI Finder · ClinicalTrials.gov</h1>
    <div class="sub">Find PIs by city/state. Lists trials via API v2, then pulls PI names via classic API v1 per NCT ID.</div>
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
          <input class="input" type="number" name="max" value="{{max or 60}}">
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
        <span class="muted">Fetched (list via v2): {{fetched}} · City-matched: {{matched}} · With PI names: {{rows|length}}</span>
      </div>

      {% if error %}
        <div class="mt8 err">Error: {{error}}</div>
      {% elif not tried %}
        <div class="muted mt8">Enter a city and click Search.</div>
      {% elif rows|length == 0 %}
        <div class="muted mt8">No PI names were returned for matched trials. Try removing Condition/Phase or increasing Max.</div>
      {% endif %}

      <div class="mt8 small">
        <div><strong>Diagnostics</strong> — v2 list endpoint: <code>{{v2_url}}</code></div>
        <div>classic v1 detail endpoint used per trial: <code>https://classic.clinicaltrials.gov/api/query/full_studies?expr=NCTXXXXX&min_rnk=1&max_rnk=1&fmt=json</code></div>
        {% if v1_errors %}
          <div class="err">Sample v1 errors (first 2):</div>
          <ul>
            {% for e in v1_errors[:2] %}
              <li class="err">{{e}}</li>
            {% endfor %}
          </ul>
        {% elif tried %}
          <div class="ok">v1 detail calls: {{v1_calls}} ok</div>
        {% endif %}
      </div>

      {% if rows %}
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

# ---------- Helpers ----------

def v2_list(expr: str, page_size: int = 200):
    """Get a broad list of studies using the modern v2 API."""
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
    """Check locations for a city/state hit."""
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

def v1_officials_by_nct(nct_id: str):
    """
    For a single trial, call classic v1 to get Overall Officials (incl PI).
    """
    # Use single-study fetch via NCT id
    params = {"expr": nct_id, "min_rnk": 1, "max_rnk": 1, "fmt": "json"}
    r = requests.get(API_V1_FULL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    try:
        proto = data["FullStudiesResponse"]["FullStudies"][0]["Study"]["ProtocolSection"]
        mod = proto.get("ContactsLocationsModule", {}) or {}
        # Standard location list
        # Officials list variants
        offs = (mod.get("OverallOfficialList", {}) or {}).get("OverallOfficial", []) or []
        if not offs:
            offs = mod.get("OverallOfficials", []) or []
    except Exception:
        return []

    out = []
    for off in offs or []:
        name = off.get("OverallOfficialName") or off.get("OfficialName") or ""
        role = off.get("OverallOfficialRole") or off.get("OfficialRole") or ""
        aff  = off.get("OverallOfficialAffiliation") or off.get("OfficialAffiliation") or ""
        if name and role and ROLE_RX.search(role):
            out.append({"name": name, "role": role, "affiliation": aff})
    return out

def get_text(proto, path: list, default=""):
    m = proto
    try:
        for k in path:
            m = m.get(k, {})
    except Exception:
        return default
    return m or default

def title_status_phase(study_v2: dict):
    proto = study_v2.get("protocolSection", {}) or {}
    idm = proto.get("identificationModule", {}) or {}
    title = idm.get("officialTitle") or idm.get("briefTitle") or ""
    status = (proto.get("statusModule", {}) or {}).get("overallStatus") or ""
    phases = proto.get("designModule", {}).get("phases") or []
    phases_text = ";".join(phases) if isinstance(phases, list) else (phases or "")
    return title, status, phases_text

# ---------- Routes ----------

@app.route("/")
def home():
    city = request.args.get("city", "")
    tried = bool(city)
    state = request.args.get("state", "")
    condition = request.args.get("condition", "")
    phase = request.args.get("phase", "any")
    max_trials = int(request.args.get("max", "60") or "60")

    rows = []
    fetched = matched = 0
    error = ""
    v1_errors = []
    v1_calls_ok = 0
    v2_url = ""

    if tried:
        try:
            terms = " ".join([t for t in [city, state, condition, (phase if phase and phase.lower() != "any" else "")] if t]).strip() or city
            studies_v2, v2_url = v2_list(terms, page_size=min(max_trials, 200))
            fetched = len(studies_v2)

            # city/state filter
            matched_pairs = []
            for s in studies_v2:
                loc = match_city_state(s, city, state)
                if loc[0] is not None:
                    matched_pairs.append((s, loc))
            matched = len(matched_pairs)

            # per-trial PI lookup via classic v1
            for s, (c_city, c_state) in matched_pairs[:max_trials]:
                nct = (s.get("protocolSection", {}).get("identificationModule", {}) or {}).get("nctId") or s.get("nctId") or ""
                if not nct:
                    continue
                try:
                    officials = v1_officials_by_nct(nct)
                    if officials:
                        title, status, phases = title_status_phase(s)
                        for off in officials:
                            rows.append({
                                "pi_name": off["name"],
                                "role": off["role"],
                                "affiliation": off.get("affiliation",""),
                                "city": c_city, "state": c_state,
                                "nct_id": nct, "status": status, "phases": phases,
                                "study_title": title, "source": "v1.overall_officials"
                            })
                        v1_calls_ok += 1
                except Exception as e:
                    v1_errors.append(f"{nct}: {type(e).__name__}: {e}")
                time.sleep(0.05)  # gentle pacing
            # dedupe by (name, city, state)
            seen = set(); deduped = []
            for r in rows:
                key = (r["pi_name"].lower(), (r["city"] or "").lower(), (r["state"] or "").lower())
                if key in seen: continue
                seen.add(key); deduped.append(r)
            rows = deduped

        except Exception as e:
            error = str(e)

    export_url = f"/export?city={city}&state={state}&condition={condition}&phase={phase}&max={max_trials}"
    return render_template_string(PAGE,
        city=city, state=state, condition=condition, phase=phase, max=max_trials,
        rows=rows, fetched=fetched, matched=matched, tried=tried, error=error,
        v1_errors=v1_errors, v1_calls=v1_calls_ok, v2_url=v2_url,
        export_url=export_url
    )

@app.route("/export")
def export():
    # re-run the same logic quickly to generate CSV
    with app.test_request_context("/", query_string=request.query_string.decode()):
        resp = home()
        # render_template_string returns HTML; we need the data again.
    # Easiest: redo minimal fetch for CSV
    city = request.args.get("city", "")
    state = request.args.get("state", "")
    condition = request.args.get("condition", "")
    phase = request.args.get("phase", "any")
    max_trials = int(request.args.get("max", "60") or "60")

    terms = " ".join([t for t in [city, state, condition, (phase if phase and phase.lower() != "any" else "")] if t]).strip() or city
    studies_v2, _ = v2_list(terms, page_size=min(max_trials, 200))

    rows = []
    for s in studies_v2:
        loc = match_city_state(s, city, state)
        if loc[0] is None:
            continue
        nct = (s.get("protocolSection", {}).get("identificationModule", {}) or {}).get("nctId") or s.get("nctId") or ""
        if not nct:
            continue
        try:
            officials = v1_officials_by_nct(nct)
            if officials:
                title, status, phases = title_status_phase(s)
                for off in officials:
                    rows.append({
                        "pi_name": off["name"], "role": off["role"], "affiliation": off.get("affiliation",""),
                        "city": loc[0], "state": loc[1], "nct_id": nct, "status": status, "phases": phases,
                        "study_title": title, "source": "v1.overall_officials"
                    })
        except Exception:
            pass
        time.sleep(0.02)

    # CSV stream
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
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# Render start: gunicorn app:app --bind 0.0.0.0:$PORT --timeout 300
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
