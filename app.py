def fetch_officials_v1(nct_id):
    """
    Use the v1 Full Studies API to get Overall Officials (includes PI names).
    """
    url = f"https://clinicaltrials.gov/api/query/full_studies?expr={nct_id}&min_rnk=1&max_rnk=1&fmt=json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    # Navigate to OverallOfficials list
    try:
        fs = data["FullStudiesResponse"]["FullStudies"][0]["Study"]["ProtocolSection"]
        officials = fs.get("ContactsLocationsModule", {}).get("OverallOfficials", [])
    except Exception:
        officials = []

    out = []
    for off in officials or []:
        name = off.get("OfficialName") or ""
        role = off.get("OfficialRole") or ""
        aff  = off.get("OfficialAffiliation") or ""
        if not name or not role:
            continue
        # Keep common investigator roles
        if re.search(r"(principal\s*investigator|study\s*chair|study\s*director|sub-?investigator)", role, re.I):
            out.append({"name": name, "role": role, "affiliation": aff})
    return out
