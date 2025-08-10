import requests
from bs4 import BeautifulSoup
from flask import Flask, request, render_template_string
import time

app = Flask(__name__)

# HTML template (kept inline for simplicity)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>PI Finder</title>
</head>
<body>
    <h1>Principal Investigator Finder</h1>
    <form method="get">
        City: <input name="city" value="{{ request.args.get('city', '') }}">
        State: <input name="state" value="{{ request.args.get('state', '') }}">
        Condition: <input name="condition" value="{{ request.args.get('condition', '') }}">
        Phase:
        <select name="phase">
            <option value="any">Any</option>
            <option value="Phase 1">Phase 1</option>
            <option value="Phase 2">Phase 2</option>
            <option value="Phase 3">Phase 3</option>
        </select>
        Max trials: <input name="max" value="{{ request.args.get('max', '50') }}">
        <button type="submit">Search</button>
    </form>

    {% if results %}
        <p>Fetched: {{ fetched }} · City-matched: {{ matched }} · With PI names: {{ with_pi }}</p>
        <table border="1" cellpadding="5">
            <tr><th>PI Name</th><th>City</th><th>State</th><th>Trial Title</th><th>Link</th></tr>
            {% for row in results %}
                <tr>
                    <td>{{ row['pi'] }}</td>
                    <td>{{ row['city'] }}</td>
                    <td>{{ row['state'] }}</td>
                    <td>{{ row['title'] }}</td>
                    <td><a href="{{ row['url'] }}" target="_blank">View</a></td>
                </tr>
            {% endfor %}
        </table>
    {% elif fetched %}
        <p>No PI results yet. Try widening your search or removing filters.</p>
    {% endif %}
</body>
</html>
"""

def fetch_trials(city, state, condition, phase, max_trials=50):
    base_url = "https://clinicaltrials.gov/api/query/study_fields"
    params = {
        "expr": f"{condition or ''} AND {city or ''} AND {state or ''}",
        "fields": "NCTId,BriefTitle,LocationCity,LocationState,OverallOfficialName,Phase",
        "min_rnk": 1,
        "max_rnk": max_trials,
        "fmt": "json"
    }
    r = requests.get(base_url, params=params)
    data = r.json()
    return data["StudyFieldsResponse"]["StudyFields"]

def scrape_pi_from_page(nct_id):
    """Fetch PI name from the trial detail page if missing in API."""
    url = f"https://clinicaltrials.gov/study/{nct_id}"
    r = requests.get(url)
    soup = BeautifulSoup(r.text, "html.parser")

    # Look for 'Principal Investigator' label
    pi_label = soup.find(text=lambda t: t and "Principal Investigator" in t)
    if pi_label:
        pi_tag = pi_label.find_parent().find_next_sibling()
        if pi_tag:
            return pi_tag.get_text(strip=True)
    return None

@app.route("/", methods=["GET"])
def home():
    city = request.args.get("city", "")
    state = request.args.get("state", "")
    condition = request.args.get("condition", "")
    phase = request.args.get("phase", "any")
    max_trials = int(request.args.get("max", "50"))

    results = []
    fetched = matched = with_pi = 0

    if city or condition:
        studies = fetch_trials(city, state, condition, phase, max_trials)
        fetched = len(studies)

        for s in studies:
            trial_city = s["LocationCity"][0] if s["LocationCity"] else ""
            trial_state = s["LocationState"][0] if s["LocationState"] else ""
            if city.lower() in trial_city.lower():
                matched += 1
                pi_name = s["OverallOfficialName"][0] if s["OverallOfficialName"] else None

                if not pi_name:
                    # Scrape the trial page to try to find PI
                    pi_name = scrape_pi_from_page(s["NCTId"][0])
                    time.sleep(1)  # be gentle to the server

                if pi_name:
                    with_pi += 1
                    results.append({
                        "pi": pi_name,
                        "city": trial_city,
                        "state": trial_state,
                        "title": s["BriefTitle"][0] if s["BriefTitle"] else "",
                        "url": f"https://clinicaltrials.gov/study/{s['NCTId'][0]}"
                    })

    return render_template_string(HTML_TEMPLATE,
                                  results=results,
                                  fetched=fetched,
                                  matched=matched,
                                  with_pi=with_pi,
                                  request=request)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
