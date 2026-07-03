import requests
from pprint import pprint

FHIR_BASE_URL = "http://hapi.fhir.org/baseR4"

# HL7 (v6.02) Code System: V2-0074 Active as of 2019-12-01: https://terminology.hl7.org/6.0.2/CodeSystem-v2-0074.html
# Basic query to fetch DiagnosticReports
diagnostic_url = f"{FHIR_BASE_URL}/DiagnosticReport"
params = {
    "category": "http://terminology.hl7.org/CodeSystem/v2-0074|RAD",  # RAD stands for Radiology
    #'identifier:exists': 'true', # this doesn't work
    "status": "final",
    # 'category': 'http://terminology.hl7.org/CodeSystem/v2-0074|LAB',  # Lab stands for Laboratory
    # 'category': 'http://terminology.hl7.org/CodeSystem/v2-0074|MB',  # MB stands for Microbiology
    # 'category': 'http://terminology.hl7.org/CodeSystem/v2-0074|PAT',  # PAT stands for Pathology
    "_count": 500,  # there are 500 diagnostic reports in total on server
}

response = requests.get(diagnostic_url, params=params)

if response.status_code != 200:
    print(f"Failed to fetch diagnostic reports. Status code: {response.status_code}")
    exit(1)

reports = response.json()

# Check if 'total' is present in the response
total_reports = reports.get("total", len(reports.get("entry", [])))

print(f"Total RADIOLOGY Diagnostic Reports Retrieved: {total_reports}")

studies = 0

for entry in reports.get("entry", []):
    report = entry["resource"]

    if (
        "identifier" not in report or "contained" not in report
    ):  # No PACS reference / Accession Number
        continue

    if "code" in report:
        print("***")
        pprint(report["code"])
    else:
        print("No diagnostic code found in this report.")

    studies += 1

    if "presentedForm" in report:
        for form in report["presentedForm"]:
            if "data" in form:
                form["data"] = f'<{form['contentType']} encoded data>'

    pprint(report)


print(f"Total Studies with identifiers: {studies}")
