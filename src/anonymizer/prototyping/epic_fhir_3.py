import requests
import ssl
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs

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
    params.update({"code_challenge": code_challenge, "code_challenge_method": code_challenge_method})

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
            else:
                print(f"Failed to retrieve access token. Status: {response.status_code}")
                print("Response:", response.text)
        except Exception as e:
            print("Error exchanging authorization code for access token:", str(e))


# Start HTTPS Server with SSLContext
def start_server():
    server_address = ("127.0.0.1", 8765)
    httpd = HTTPServer(server_address, CallbackHandler)

    # Create SSL context
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(certfile="src/certs/cert.pem", keyfile="src/certs/key.pem")

    # Wrap the server's socket with SSL
    httpd.socket = ssl_context.wrap_socket(httpd.socket, server_side=True)

    print("Server running at https://127.0.0.1:8765/callback...")

    print("Opening the browser to authenticate...")
    webbrowser.open(url)

    httpd.serve_forever()


if __name__ == "__main__":
    start_server()
