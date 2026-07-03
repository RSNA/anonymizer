import requests
import ssl
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs
from pprint import pprint

# Epic OAuth2 authorization and token endpoint
authorize_url = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize"
token_url = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"

# Client-specific details
client_id = "19875d40-5c73-4a7f-9d0b-78015ca70f05"
redirect_uri = "https://127.0.0.1:8765/callback"
state = "random_state_value"  # Optional but recommended
scope = "openid fhirUser"  # Required for Epic
base_aud = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/"  # The base FHIR server URL

# Additional parameters for PKCE (if required)
code_challenge = None  # Replace with your S256 hashed value if using PKCE
code_challenge_method = "S256"  # Optional, required if using code_challenge

# Build the authorization request
params = {
    "response_type": "code",
    "client_id": client_id,
    "redirect_uri": redirect_uri,
    "state": state,
    "scope": scope,
    "aud": base_aud,
}

if code_challenge:
    params.update(
        {
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        }
    )

# Construct the full URL
url = f"{authorize_url}?{urlencode(params)}"


# HTTP Request Handler
class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urlparse(self.path).query
        params = parse_qs(query)

        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorization code received. Check the console.")
            print(f"Authorization code: {auth_code}")
            # Exchange the authorization code for an access token
            self.exchange_auth_code(auth_code)
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Authorization code not found in the request.")

    def exchange_auth_code(self, auth_code):
        data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        print("Exchanging authorization code for access token...")
        try:
            response = requests.post(token_url, data=data, headers=headers)
            if response.status_code == 200:
                token_response = response.json()
                print("Access token received:")
                print(token_response)
                save_access_token(token_response["access_token"])
                # Fetch FHIR patient data using the access token
                run_test(token_response["access_token"])
            else:
                print(f"Failed to retrieve access token. Status: {response.status_code}")
                print("Response:", response.text)
        except Exception as e:
            print("Error exchanging authorization code for access token:", str(e))


def fetch_diagnostic_reports(access_token):
    # Failed to retrieve patient data. Status: 400
    # {'issue': [{'code': 'business-rule',
    #             'details': {'coding': [{'code': '59159',
    #                                     'display': 'The content/operation failed '
    #                                                'to pass a business rule, and '
    #                                                'so could not proceed.',
    #                                     'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.2.657369'}],
    #                         'text': 'The content/operation failed to pass a '
    #                                 'business rule, and so could not proceed.'},
    #             'diagnostics': 'This resource requires a patient or _id parameter '
    #                            'for searching.',
    #             'expression': ['patient/_id'],
    #             'location': ['/f:patient/_id'],
    #             'severity': 'fatal'}],
    #  'resourceType': 'OperationOutcome'}

    # HL7 (v6.02) Code System: V2-0074 Active as of 2019-12-01: https://terminology.hl7.org/6.0.2/CodeSystem-v2-0074.html
    # Basic query to fetch DiagnosticReports
    diagnostic_url = f"{base_aud}/DiagnosticReport"
    fhir_rad_params = {
        "category": "http://terminology.hl7.org/CodeSystem/v2-0074|RAD",  # RAD stands for Radiology
        #'identifier:exists': 'true', # this doesn't work
        "status": "final",
        # 'category': 'http://terminology.hl7.org/CodeSystem/v2-0074|LAB',  # Lab stands for Laboratory
        # 'category': 'http://terminology.hl7.org/CodeSystem/v2-0074|MB',  # MB stands for Microbiology
        # 'category': 'http://terminology.hl7.org/CodeSystem/v2-0074|PAT',  # PAT stands for Pathology
        "_count": 5,  # there are 2 diagnostic reports on EPIC sandbox server as of Nov 2024
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/fhir+json",
    }

    print("FHIR Query for Diagnostic reports...")
    try:
        response = requests.get(diagnostic_url, headers=headers, params=fhir_rad_params)
        if response.status_code == 200:
            print("Diagnostic Report data retrieved successfully:")
            pprint(response.json())
            reports = response.json()
            # Check if 'total' is present in the response
            total_reports = reports.get("total", len(reports.get("entry", [])))
            pprint(f"Total RADIOLOGY Diagnostic Reports Retrieved: {total_reports}")
        else:
            print(f"Failed to retrieve patient data. Status: {response.status_code}")
            pprint(response.json())
    except Exception as e:
        print("Error fetching patient data:", str(e))


def fetch_patient_record(access_token, fhir_patient_id: str):
    # Patient data retrieved successfully:
    # {'active': True,
    #  'address': [{'city': 'GARLAND',
    #               'country': 'US',
    #               'district': 'DALLAS',
    #               'line': ['3268 West Johnson St.', 'Apt 117'],
    #               'period': {'start': '2019-05-24'},
    #               'postalCode': '75043',
    #               'state': 'TX',
    #               'use': 'home'},
    #              {'city': 'GARLAND',
    #               'country': 'US',
    #               'district': 'DALLAS',
    #               'line': ['3268 West Johnson St.', 'Apt 117'],
    #               'postalCode': '75043',
    #               'state': 'TX',
    #               'use': 'old'}],
    #  'birthDate': '1987-09-12',
    #  'communication': [{'language': {'coding': [{'code': 'en',
    #                                              'display': 'English',
    #                                              'system': 'urn:ietf:bcp:47'}],
    #                                  'text': 'English'},
    #                     'preferred': True}],
    #  'deceasedBoolean': False,
    #  'extension': [{'url': 'http://open.epic.com/FHIR/StructureDefinition/extension/legal-sex',
    #                 'valueCodeableConcept': {'coding': [{'code': 'female',
    #                                                      'display': 'female',
    #                                                      'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.10.698084.130.657370.19999000'}]}},
    #                {'url': 'http://open.epic.com/FHIR/StructureDefinition/extension/sex-for-clinical-use',
    #                 'valueCodeableConcept': {'coding': [{'code': 'female',
    #                                                      'display': 'female',
    #                                                      'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.10.698084.130.657370.19999000'}]}},
    #                {'extension': [{'url': 'ombCategory',
    #                                'valueCoding': {'code': '2131-1',
    #                                                'display': 'Other Race',
    #                                                'system': 'urn:oid:2.16.840.1.113883.6.238'}},
    #                               {'url': 'text', 'valueString': 'Other'}],
    #                 'url': 'http://hl7.org/fhir/us/core/StructureDefinition/us-core-race'},
    #                {'extension': [{'url': 'text', 'valueString': 'Unknown'}],
    #                 'url': 'http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity'},
    #                {'url': 'http://hl7.org/fhir/us/core/StructureDefinition/us-core-sex',
    #                 'valueCode': '248152002'},
    #                {'url': 'http://open.epic.com/FHIR/StructureDefinition/extension/calculated-pronouns-to-use-for-text',
    #                 'valueCodeableConcept': {'coding': [{'code': 'LA29519-8',
    #                                                      'display': 'she/her/her/hers/herself',
    #                                                      'system': 'http://loinc.org'}]}}],
    #  'gender': 'female',
    #  'generalPractitioner': [{'display': 'Physician Family Medicine, MD',
    #                           'reference': 'Practitioner/eM5CWtq15N0WJeuCet5bJlQ3',
    #                           'type': 'Practitioner'}],
    #  'id': 'erXuFYUfucBZaryVksYEcMg3',
    #  'identifier': [{'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.3.688884.100',
    #                  'type': {'text': 'CEID'},
    #                  'use': 'usual',
    #                  'value': 'FHRFZ2F59MDNXBV'},
    #                 {'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.5.737384.0',
    #                  'type': {'text': 'EPIC'},
    #                  'use': 'usual',
    #                  'value': 'E4007'},
    #                 {'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.2.698084',
    #                  'type': {'text': 'EXTERNAL'},
    #                  'use': 'usual',
    #                  'value': 'Z6129'},
    #                 {'system': 'http://open.epic.com/FHIR/StructureDefinition/patient-dstu2-fhir-id',
    #                  'type': {'text': 'FHIR'},
    #                  'use': 'usual',
    #                  'value': 'TnOZ.elPXC6zcBNFMcFA7A5KZbYxo2.4T-LylRk4GoW4B'},
    #                 {'system': 'http://open.epic.com/FHIR/StructureDefinition/patient-fhir-id',
    #                  'type': {'text': 'FHIR STU3'},
    #                  'use': 'usual',
    #                  'value': 'erXuFYUfucBZaryVksYEcMg3'},
    #                 {'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.2.698084',
    #                  'type': {'text': 'INTERNAL'},
    #                  'use': 'usual',
    #                  'value': '     Z6129'},
    #                 {'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.5.737384.14',
    #                  'type': {'text': 'EPI'},
    #                  'use': 'usual',
    #                  'value': '203713'},
    #                 {'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.3.878082.110',
    #                  'type': {'text': 'MYCHARTLOGIN'},
    #                  'use': 'usual',
    #                  'value': 'FHIRCAMILA'},
    #                 {'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.2.878082',
    #                  'type': {'text': 'WPRINTERNAL'},
    #                  'use': 'usual',
    #                  'value': '736'}],
    #  'managingOrganization': {'display': 'Epic Hospital System',
    #                           'reference': 'Organization/enRyWnSP963FYDpoks4NHOA3'},
    #  'maritalStatus': {'text': 'Married'},
    #  'name': [{'family': 'Lopez',
    #            'given': ['Camila', 'Maria'],
    #            'text': 'Camila Maria Lopez',
    #            'use': 'official'},
    #           {'family': 'Lopez',
    #            'given': ['Camila', 'Maria'],
    #            'text': 'Camila Maria Lopez',
    #            'use': 'usual'}],
    #  'resourceType': 'Patient',
    #  'telecom': [{'system': 'phone', 'use': 'home', 'value': '469-555-5555'},
    #              {'system': 'phone', 'use': 'work', 'value': '469-888-8888'},
    #              {'rank': 1,
    #               'system': 'email',
    #               'value': 'knixontestemail@epic.com'}]}

    patient_url = f"{base_aud}/patient/{fhir_patient_id}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/fhir+json",
    }

    print(f"FHIR Query for Patient: {fhir_patient_id}...")
    try:
        response = requests.get(patient_url, headers=headers)
        if response.status_code == 200:
            print("Patient data retrieved successfully:")
            pprint(response.json())
        else:
            print(f"Failed to retrieve patient data. Status: {response.status_code}")
            pprint(response.json())
    except Exception as e:
        print("Error fetching patient data:", str(e))


def fetch_patient_diagnostic_reports(access_token, patient_id):
    # FHIR Query for Diagnostic reports for patient: erXuFYUfucBZaryVksYEcMg3...
    # Diagnostic Reports retrieved successfully:
    # {'entry': [{'fullUrl': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport/elx1Jshr9qLOD4ufQ74qBMUFrwtMOcB1Xr9An7ASZR-83',
    #             'link': [{'relation': 'self',
    #                       'url': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport/elx1Jshr9qLOD4ufQ74qBMUFrwtMOcB1Xr9An7ASZR-83'}],
    #             'resource': {'basedOn': [{'display': 'CBC and differential',
    #                                       'reference': 'ServiceRequest/eK6sCsSKqfbW3Mps-9UTttzTXimr.hD8JVMCVQTY8yMo3'}],
    #                          'category': [{'coding': [{'code': 'Lab',
    #                                                    'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.10.798268.30'}],
    #                                        'text': 'Lab'},
    #                                       {'coding': [{'code': 'LAB',
    #                                                    'display': 'Laboratory',
    #                                                    'system': 'http://terminology.hl7.org/CodeSystem/v2-0074'}],
    #                                        'text': 'Laboratory'}],
    #                          'code': {'coding': [{'code': '1696',
    #                                               'display': 'CBC AND DIFFERENTIAL',
    #                                               'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.2.696580'},
    #                                              {'code': '9564003',
    #                                               'display': 'CBC AND DIFFERENTIAL',
    #                                               'system': 'urn:oid:2.16.840.1.113883.6.96'}],
    #                                   'text': 'CBC and differential'},
    #                          'effectiveDateTime': '2019-05-28T14:21:00Z',
    #                          'encounter': {'display': 'Office Visit',
    #                                        'identifier': {'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.3.698084.8',
    #                                                       'use': 'usual',
    #                                                       'value': '27558'},
    #                                        'reference': 'Encounter/elMz2mwjsRvKnZiR.0ceTUg3'},
    #                          'id': 'elx1Jshr9qLOD4ufQ74qBMUFrwtMOcB1Xr9An7ASZR-83',
    #                          'identifier': [{'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.2.798268',
    #                                          'type': {'coding': [{'code': 'PLAC',
    #                                                               'display': 'Placer '
    #                                                                          'Identifier',
    #                                                               'system': 'http://terminology.hl7.org/CodeSystem/v2-0203'}],
    #                                                   'text': 'Placer Identifier'},
    #                                          'use': 'official',
    #                                          'value': '1066900'}],
    #                          'issued': '2019-05-28T14:21:00Z',
    #                          'performer': [{'display': 'Physician Family Medicine, '
    #                                                    'MD',
    #                                         'reference': 'Practitioner/eM5CWtq15N0WJeuCet5bJlQ3',
    #                                         'type': 'Practitioner'}],
    #                          'resourceType': 'DiagnosticReport',
    #                          'result': [{'display': 'Component (1): '
    #                                                 'LEUKOCYTES(10*3/UL) IN BLOOD '
    #                                                 'BY AUTOMATED COUNT',
    #                                      'reference': 'Observation/efdH9KfkpL80Id0L6JfDK5LO-yyDW4ziEBQtZ3.RMbNjen0QdebiGe502pCPQ4-9I3'},
    #                                     {'display': 'Component (1): ERYTHROCYTES '
    #                                                 '(10*6/UL) IN BLOOD BY '
    #                                                 'AUTOMATED COUNT',
    #                                      'reference': 'Observation/efdH9KfkpL80Id0L6JfDK5LO-yyDW4ziEBQtZ3.RMbNiZYMaZC4SMjWZa2lcoygsB3'},
    #                                     {'display': 'Component (1): PLATELETS '
    #                                                 '(10*3/UL) IN BLOOD AUTOMATED '
    #                                                 'COUNT',
    #                                      'reference': 'Observation/efdH9KfkpL80Id0L6JfDK5LO-yyDW4ziEBQtZ3.RMbNjuRJ.TpTgtETGg6K0LfRGG3'}],
    #                          'status': 'amended',
    #                          'subject': {'display': 'Lopez, Camila Maria',
    #                                      'reference': 'Patient/erXuFYUfucBZaryVksYEcMg3'}},
    #             'search': {'mode': 'match'}},
    #            {'fullUrl': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport/ebLG6RMUaZyb2xk2DuX.kd4g8mNRffn9ftcwqSmnhrwM3',
    #             'link': [{'relation': 'self',
    #                       'url': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport/ebLG6RMUaZyb2xk2DuX.kd4g8mNRffn9ftcwqSmnhrwM3'}],
    #             'resource': {'basedOn': [{'display': 'Hemoglobin A1c',
    #                                       'reference': 'ServiceRequest/egf4KkhXmgeVWImXEEYH.CEE1ZgJG5SQy2vBX1HgvBCs3'}],
    #                          'category': [{'coding': [{'code': 'Lab',
    #                                                    'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.10.798268.30'}],
    #                                        'text': 'Lab'},
    #                                       {'coding': [{'code': 'LAB',
    #                                                    'display': 'Laboratory',
    #                                                    'system': 'http://terminology.hl7.org/CodeSystem/v2-0074'}],
    #                                        'text': 'Laboratory'}],
    #                          'code': {'coding': [{'code': '4548-4',
    #                                               'system': 'http://loinc.org'},
    #                                              {'code': '83036',
    #                                               'display': 'PR GLYCOSYLATED '
    #                                                          'HEMOGLOBIN TEST',
    #                                               'system': 'urn:oid:2.16.840.1.113883.6.12'},
    #                                              {'code': '43396009',
    #                                               'display': 'HEMOGLOBIN A1C',
    #                                               'system': 'urn:oid:2.16.840.1.113883.6.96'}],
    #                                   'text': 'Hemoglobin A1c'},
    #                          'effectiveDateTime': '2019-05-28T14:22:00Z',
    #                          'encounter': {'display': 'Office Visit',
    #                                        'identifier': {'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.3.698084.8',
    #                                                       'use': 'usual',
    #                                                       'value': '27558'},
    #                                        'reference': 'Encounter/elMz2mwjsRvKnZiR.0ceTUg3'},
    #                          'id': 'ebLG6RMUaZyb2xk2DuX.kd4g8mNRffn9ftcwqSmnhrwM3',
    #                          'identifier': [{'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.2.798268',
    #                                          'type': {'coding': [{'code': 'PLAC',
    #                                                               'display': 'Placer '
    #                                                                          'Identifier',
    #                                                               'system': 'http://terminology.hl7.org/CodeSystem/v2-0203'}],
    #                                                   'text': 'Placer Identifier'},
    #                                          'use': 'official',
    #                                          'value': '1066905'}],
    #                          'issued': '2019-05-28T14:22:00Z',
    #                          'performer': [{'display': 'Physician Family Medicine, '
    #                                                    'MD',
    #                                         'reference': 'Practitioner/eM5CWtq15N0WJeuCet5bJlQ3',
    #                                         'type': 'Practitioner'}],
    #                          'resourceType': 'DiagnosticReport',
    #                          'result': [{'display': 'Component (1): HEMOGLOBIN '
    #                                                 'A1C, POC',
    #                                      'reference': 'Observation/eyPMWgv2u2RUfsV4p1lLKuUtqyPs2-QNi2zKvbTsFYtRByc6B.cSi1iVU5V2HOpX23'}],
    #                          'status': 'final',
    #                          'subject': {'display': 'Lopez, Camila Maria',
    #                                      'reference': 'Patient/erXuFYUfucBZaryVksYEcMg3'}},
    #             'search': {'mode': 'match'}},
    #            {'fullUrl': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport/eH7uO.T7OPCIuALe7p47ChPK3TH5CVepY16FOxdmht6U3',
    #             'link': [{'relation': 'self',
    #                       'url': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport/eH7uO.T7OPCIuALe7p47ChPK3TH5CVepY16FOxdmht6U3'}],
    #             'resource': {'basedOn': [{'display': 'Pharmacogenomic Panel',
    #                                       'reference': 'ServiceRequest/eikKnNjBSfWHmf2MZw5cvxvZudUUagi02jRCL-GG9YXA3'}],
    #                          'category': [{'coding': [{'code': 'Lab',
    #                                                    'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.10.798268.30'}],
    #                                        'text': 'Lab'},
    #                                       {'coding': [{'code': 'LAB',
    #                                                    'display': 'Laboratory',
    #                                                    'system': 'http://terminology.hl7.org/CodeSystem/v2-0074'}],
    #                                        'text': 'Laboratory'}],
    #                          'code': {'coding': [{'code': 'LAB10052',
    #                                               'display': 'PHARMACOGENOMICS '
    #                                                          'PANEL',
    #                                               'system': 'urn:oid:2.16.840.1.113883.6.12'}],
    #                                   'text': 'Pharmacogenomic Panel'},
    #                          'effectiveDateTime': '2023-03-21T21:42:00Z',
    #                          'encounter': {'display': 'Office Visit',
    #                                        'identifier': {'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.3.698084.8',
    #                                                       'use': 'usual',
    #                                                       'value': '27558'},
    #                                        'reference': 'Encounter/elMz2mwjsRvKnZiR.0ceTUg3'},
    #                          'id': 'eH7uO.T7OPCIuALe7p47ChPK3TH5CVepY16FOxdmht6U3',
    #                          'identifier': [{'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.2.798268',
    #                                          'type': {'coding': [{'code': 'PLAC',
    #                                                               'display': 'Placer '
    #                                                                          'Identifier',
    #                                                               'system': 'http://terminology.hl7.org/CodeSystem/v2-0203'}],
    #                                                   'text': 'Placer Identifier'},
    #                                          'use': 'official',
    #                                          'value': '1066906'}],
    #                          'issued': '2023-03-21T21:42:00Z',
    #                          'performer': [{'display': 'Attending Physician '
    #                                                    'Inpatient, MD',
    #                                         'reference': 'Practitioner/e9s-IdXQOUVywHOVoisd6xQ3',
    #                                         'type': 'Practitioner'}],
    #                          'resourceType': 'DiagnosticReport',
    #                          'result': [{'display': 'Component (1): GENOTYPE:',
    #                                      'reference': 'Observation/e2wla.p-cP3wLJKzvkSyXg-uK6m.vmaiIZWz53hK7wkC2t82hC1heHjjJ5ty1bqd.3'}],
    #                          'status': 'final',
    #                          'subject': {'display': 'Lopez, Camila Maria',
    #                                      'reference': 'Patient/erXuFYUfucBZaryVksYEcMg3'}},
    #             'search': {'mode': 'match'}},
    #            {'fullUrl': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport/eVgy7plRONpRD4mfON6.ghhhvltp5gZc8m7Deq8R2q7o3',
    #             'link': [{'relation': 'self',
    #                       'url': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport/eVgy7plRONpRD4mfON6.ghhhvltp5gZc8m7Deq8R2q7o3'}],
    #             'resource': {'basedOn': [{'display': 'Pharmacogenomic Panel',
    #                                       'reference': 'ServiceRequest/egSVxzEQTsjKgW6Dx6veENM8MSbquRNB41NDAnmTfdEc3'}],
    #                          'category': [{'coding': [{'code': 'Lab',
    #                                                    'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.10.798268.30'}],
    #                                        'text': 'Lab'},
    #                                       {'coding': [{'code': 'LAB',
    #                                                    'display': 'Laboratory',
    #                                                    'system': 'http://terminology.hl7.org/CodeSystem/v2-0074'}],
    #                                        'text': 'Laboratory'}],
    #                          'code': {'coding': [{'code': 'LAB10052',
    #                                               'display': 'PHARMACOGENOMICS '
    #                                                          'PANEL',
    #                                               'system': 'urn:oid:2.16.840.1.113883.6.12'}],
    #                                   'text': 'Pharmacogenomic Panel'},
    #                          'effectiveDateTime': '2023-03-28T05:00:00Z',
    #                          'encounter': {'display': 'Office Visit',
    #                                        'identifier': {'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.3.698084.8',
    #                                                       'use': 'usual',
    #                                                       'value': '27558'},
    #                                        'reference': 'Encounter/elMz2mwjsRvKnZiR.0ceTUg3'},
    #                          'id': 'eVgy7plRONpRD4mfON6.ghhhvltp5gZc8m7Deq8R2q7o3',
    #                          'identifier': [{'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.2.798268',
    #                                          'type': {'coding': [{'code': 'PLAC',
    #                                                               'display': 'Placer '
    #                                                                          'Identifier',
    #                                                               'system': 'http://terminology.hl7.org/CodeSystem/v2-0203'}],
    #                                                   'text': 'Placer Identifier'},
    #                                          'use': 'official',
    #                                          'value': '1066907'}],
    #                          'issued': '2023-03-28T21:22:00Z',
    #                          'performer': [{'display': 'Attending Physician '
    #                                                    'Inpatient, MD',
    #                                         'reference': 'Practitioner/e9s-IdXQOUVywHOVoisd6xQ3',
    #                                         'type': 'Practitioner'}],
    #                          'resourceType': 'DiagnosticReport',
    #                          'status': 'final',
    #                          'subject': {'display': 'Lopez, Camila Maria',
    #                                      'reference': 'Patient/erXuFYUfucBZaryVksYEcMg3'}},
    #             'search': {'mode': 'match'}},
    #            {'fullUrl': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport/eeIUePPFhkOlGgtsbPko4a4tPlKY9045CYysh7Ryulnc3',
    #             'link': [{'relation': 'self',
    #                       'url': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport/eeIUePPFhkOlGgtsbPko4a4tPlKY9045CYysh7Ryulnc3'}],
    #             'resource': {'basedOn': [{'display': 'X-ray Chest 2 Views',
    #                                       'reference': 'ServiceRequest/ePsXywWuaF47D-FPsxcnz3BOk1-JNF41RJJEMQu.2TCA3'}],
    #                          'category': [{'coding': [{'code': 'Imaging',
    #                                                    'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.10.798268.30'}],
    #                                        'text': 'Imaging'},
    #                                       {'coding': [{'code': 'LP29684-5',
    #                                                    'display': 'Radiology',
    #                                                    'system': 'http://loinc.org'}],
    #                                        'text': 'Radiology'}],
    #                          'code': {'coding': [{'code': '36643-5',
    #                                               'system': 'http://loinc.org'},
    #                                              {'code': '71020',
    #                                               'display': 'HC XR CHEST 2V',
    #                                               'system': 'urn:oid:2.16.840.1.113883.6.12'},
    #                                              {'code': '7000029',
    #                                               'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.5.737384.52000'},
    #                                              {'code': 'IMG36',
    #                                               'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.5.737384.72'},
    #                                              {'code': 'RPID2503',
    #                                               'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.5.737384.155'}],
    #                                   'text': 'X-ray Chest 2 Views'},
    #                          'conclusionCode': [{'coding': [{'code': '225566008',
    #                                                          'display': 'Ischemic '
    #                                                                     'chest '
    #                                                                     'pain '
    #                                                                     '(finding)',
    #                                                          'system': 'http://snomed.info/sct'},
    #                                                         {'code': '786.50',
    #                                                          'display': 'Chest '
    #                                                                     'pain, '
    #                                                                     'unspecified',
    #                                                          'system': 'http://hl7.org/fhir/sid/icd-9-cm'},
    #                                                         {'code': 'I20.9',
    #                                                          'display': 'Angina '
    #                                                                     'pectoris, '
    #                                                                     'unspecified',
    #                                                          'system': 'http://hl7.org/fhir/sid/icd-10-cm'}],
    #                                              'text': 'Ischemic chest pain '
    #                                                      '(CMS/HCC)'}],
    #                          'effectiveDateTime': '2023-06-02T20:43:46Z',
    #                          'encounter': {'display': 'Hospital Encounter',
    #                                        'identifier': {'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.3.698084.8',
    #                                                       'use': 'usual',
    #                                                       'value': '29541'},
    #                                        'reference': 'Encounter/eoIRZgvu9RhrwOzDlZkRbSg3'},
    #                          'id': 'eeIUePPFhkOlGgtsbPko4a4tPlKY9045CYysh7Ryulnc3',
    #                          'identifier': [{'system': 'urn:oid:1.2.840.114350.1.13.0.1.7.2.798268',
    #                                          'type': {'coding': [{'code': 'PLAC',
    #                                                               'display': 'Placer '
    #                                                                          'Identifier',
    #                                                               'system': 'http://terminology.hl7.org/CodeSystem/v2-0203'}],
    #                                                   'text': 'Placer Identifier'},
    #                                          'use': 'official',
    #                                          'value': '1066912'},
    #                                         {'type': {'coding': [{'code': 'FILL',
    #                                                               'display': 'Filler '
    #                                                                          'Identifier',
    #                                                               'system': 'http://terminology.hl7.org/CodeSystem/v2-0203'}],
    #                                                   'text': 'Filler Identifier'},
    #                                          'use': 'official',
    #                                          'value': '161'}],
    #                          'imagingStudy': [{'reference': 'ImagingStudy/en.FwduRkOep5gh4PDxytn-8vQD1juX2e3fuEQMe4ymw3'}],
    #                          'issued': '2023-07-25T13:27:19Z',
    #                          'performer': [{'display': 'Physician Family Medicine, '
    #                                                    'MD',
    #                                         'reference': 'Practitioner/eM5CWtq15N0WJeuCet5bJlQ3',
    #                                         'type': 'Practitioner'},
    #                                        {'display': 'Np Family Medicine, NP',
    #                                         'reference': 'Practitioner/elpRiy0AYgjhdjAhTBJ3Aiw3',
    #                                         'type': 'Practitioner'},
    #                                        {'display': 'IMAGING',
    #                                         'reference': 'Organization/etOhDRFmHqAJ3CBmvHCeF9VYgSiH5bYCNkDSOho2TXb43',
    #                                         'type': 'Organization'}],
    #                          'presentedForm': [{'contentType': 'text/html',
    #                                             'title': 'Narrative',
    #                                             'url': 'Binary/eatrFYJ-c5OxFaXGGKhRmt-kbn-1xHl8SNrcCB4fHVps3'},
    #                                            {'contentType': 'text/html',
    #                                             'title': 'Impression',
    #                                             'url': 'Binary/eatrFYJ-c5OxFaXGGKhRmtxnlc-Z0vWhRnWj621bo99g3'},
    #                                            {'contentType': 'application/pdf',
    #                                             'title': 'Study Result Document',
    #                                             'url': 'Binary/f.xEvohRYve42wOh7tEM40g4'}],
    #                          'resourceType': 'DiagnosticReport',
    #                          'result': [{'display': 'Narrative',
    #                                      'reference': 'Observation/eWQ91GjryHtrlYhSNxK1L7mI-fgFwPAedom.YQ4JDeQk3'},
    #                                     {'display': 'Impression',
    #                                      'reference': 'Observation/eWQ91GjryHtrlYhSNxK1L7hOQbiABlro0a6oo2bIh68I3'}],
    #                          'resultsInterpreter': [{'display': 'Physician Family '
    #                                                             'Medicine, MD',
    #                                                  'reference': 'Practitioner/eM5CWtq15N0WJeuCet5bJlQ3',
    #                                                  'type': 'Practitioner'}],
    #                          'status': 'final',
    #                          'subject': {'display': 'Lopez, Camila Maria',
    #                                      'reference': 'Patient/erXuFYUfucBZaryVksYEcMg3'}},
    #             'search': {'mode': 'match'}}],
    #  'link': [{'relation': 'next',
    #            'url': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport?sessionID=06-C247264DB30411EF9D99005056BECC4A'},
    #           {'relation': 'self',
    #            'url': 'https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/DiagnosticReport?patient=erXuFYUfucBZaryVksYEcMg3&_count=5'}],
    #  'resourceType': 'Bundle',
    #  'total': 5,
    #  'type': 'searchset'}

    diagnostic_url = f"{base_aud}/DiagnosticReport"
    fhir_params = {
        "patient": patient_id,  # Patient context is required
        "_count": 5,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/fhir+json",
    }

    print(f"FHIR Query for Diagnostic reports for patient: {patient_id}...")
    try:
        response = requests.get(diagnostic_url, headers=headers, params=fhir_params)
        if response.status_code == 200:
            print("Diagnostic Reports retrieved successfully:")
            pprint(response.json())
        else:
            print(f"Failed to retrieve diagnostic reports. Status: {response.status_code}")
            pprint(response.json())
    except Exception as e:
        print("Error fetching diagnostic reports:", str(e))


def fetch_patient_diagnostic_reports_by_icd(access_token, patient_id, icd_code):
    diagnostic_url = f"{base_aud}/DiagnosticReport"
    fhir_params = {
        "patient": patient_id,  # Patient context is required
        "status": "final",
        "conclusionCode": f"http://hl7.org/fhir/sid/icd-10-cm|{icd_code}",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/fhir+json",
    }

    print("FHIR Query for Diagnostic reports with ICD code...")
    try:
        response = requests.get(diagnostic_url, headers=headers, params=fhir_params)
        if response.status_code == 200:
            print("Filtered Diagnostic Report data retrieved successfully:")
            pprint(response.json())
        else:
            print(f"Failed to retrieve filtered diagnostic reports. Status: {response.status_code}")
            pprint(response.json())
    except Exception as e:
        print("Error fetching filtered diagnostic reports:", str(e))


def fetch_diagnostic_reports_by_icd(access_token, icd_code):
    diagnostic_url = f"{base_aud}/DiagnosticReport"
    fhir_params = {
        "category": "http://loinc.org|LP29684-5",  # Radiology
        "status": "final",
        "conclusionCode": f"http://hl7.org/fhir/sid/icd-10-cm|{icd_code}",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/fhir+json",
    }

    print(f"FHIR Query for Diagnostic reports with ICD code: {icd_code}...")
    try:
        response = requests.get(diagnostic_url, headers=headers, params=fhir_params)
        if response.status_code == 200:
            print("Filtered Diagnostic Report data retrieved successfully:")
            pprint(response.json())
        else:
            print(f"Failed to retrieve filtered diagnostic reports. Status: {response.status_code}")
            pprint(response.json())
    except Exception as e:
        print("Error fetching filtered diagnostic reports:", str(e))


def run_test(access_token):
    fhir_pt_id_1 = "erXuFYUfucBZaryVksYEcMg3"
    # fhir_pt_id_1_icd10 = "I20.9"
    # fetch_diagnostic_reports(access_token)
    # fetch_patient_record(access_token, fhir_pt_id_1)
    fetch_patient_diagnostic_reports(access_token, fhir_pt_id_1)
    # fetch_patient_diagnostic_reports_by_icd(access_token, fhir_pt_id_1, fhir_pt_id_1_icd10)
    # fetch_diagnostic_reports_by_icd(access_token, fhir_pt_id_1_icd10)


# Save the access token to a file
def save_access_token(token, filename="access_token.txt"):
    with open(filename, "w") as file:
        file.write(token)


# Read the access token from the file
def read_access_token(filename="access_token.txt"):
    try:
        with open(filename, "r") as file:
            return file.read().strip()
    except FileNotFoundError:
        return None


# Start HTTPS Server with SSLContext
def start_server():
    server_address = ("127.0.0.1", 8765)
    httpd = HTTPServer(server_address, CallbackHandler)

    # Create SSL context
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(
        certfile="src/anonymizer/prototyping/certs/cert.pem", keyfile="src/anonymizer/prototyping/certs/key.pem"
    )

    # Wrap the server's socket with SSL
    httpd.socket = ssl_context.wrap_socket(httpd.socket, server_side=True)

    print("Server running at https://127.0.0.1:8765/callback...")

    # if cached_access_token.txt present load it and run test without auth:
    access_token = read_access_token()
    if access_token:
        print("Using cached access token from file")
        run_test(access_token)
    else:
        print("Opening the browser to authenticate...")
        webbrowser.open(url)

    httpd.serve_forever()


if __name__ == "__main__":
    start_server()
