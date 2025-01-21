from requests_oauthlib import OAuth2Session

# https://fhir.jefferson.edu/FHIRProxy/api/FHIR/R4

# Step 1:
# https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize?response_type=code&redirect_uri=[redirect_uri]&client_id=[client_id]&state=[state]&aud=[audience]&scope=[scope]

EPIC_SANDBOX_BASE_URL = "https://fhir.epic.com/interconnect-fhir-oauth/"

FHIR_API_R4_URL = EPIC_SANDBOX_BASE_URL + "api/FHIR/R4/"

SANDBOX_CLIENT_ID = "19875d40-5c73-4a7f-9d0b-78015ca70f05"

REDIRECT_URI = "127.0.0.1:8765/callback"

authorize_url = EPIC_SANDBOX_BASE_URL + "authorize"  # OAuth2 authorize endpoint
token_url = EPIC_SANDBOX_BASE_URL + "token"  # OAuth2 token endpoint

# OAuth2 workflow:
oauth = OAuth2Session(SANDBOX_CLIENT_ID, redirect_uri=REDIRECT_URI)

# Step 1: Get authorization URL and redirect user to it
authorization_url, state = oauth.authorization_url(authorize_url)

print(f"Please go to this URL and authorize access: {authorization_url}")
