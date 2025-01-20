import requests
import webbrowser
from urllib.parse import urlencode

# Epic OAuth2 authorization endpoint
authorize_url = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize"

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
    params.update({"code_challenge": code_challenge, "code_challenge_method": code_challenge_method})

# Construct the full URL
url = f"{authorize_url}?{urlencode(params)}"

# Open the URL in a browser for the user to authenticate
print("Opening the browser to authenticate...")
webbrowser.open(url)

# Instructions for the user
print("Once authenticated, you will be redirected to your callback URI.")
print("Check the URL for a 'code' parameter and use it in the next step.")

# Note: The callback URI handler is not implemented in this script.
# You should set up a server or other mechanism to handle the redirect and capture the authorization code.
