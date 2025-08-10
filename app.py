# app.py — PI Finder using ClinicalTrials.gov Full Studies v1 for PI names
import io, csv, re
import requests
from flask import Flask, request, render_template_string, Response

API_V2_STUDY_FIELDS = "https://clinicaltrials.gov/api/query/study_fields"
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
  .card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px;box-shadow:0 1px 2px rgba(0,0,0,.03)}
  label{display:block;font-size:13px;margin-bottom:6px} input,select,button{font:in
