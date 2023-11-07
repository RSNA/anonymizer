import boto3
import qrcode

# https://www.archerimagine.com/articles/aws/aws-cognito-tutorials.html

# AWS S3 Bucket Details
client_id="46ugbt3jat1spc70ulio46btmc"
s3_bucket="amplify-datauploader-prodmi-stagingbucketeec2e4de-x4qrvyzen65z"
s3_prefix="private/"
username="anonymizer"
password="P^l-8n+(ha?$6*&3"

def authenticate_user(cognito_client, username, password):
    try:
        # Sign in with the provided credentials
        response = cognito_client.initiate_auth(
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": username,
                "PASSWORD": password,
            },
            ClientId=client_id,
        )
        print(response)

        if 'ChallengeName' in response and response['ChallengeName'] == 'MFA_SETUP':
            # MFA setup required
            qr_code = response['Session']
            print("QR Code for MFA setup:", qr_code)
            img = qrcode.make(qr_code)
            img.save("mfa_qr_code.png")
            print("mfa qr code saved to mfa_qr_code.png")
        else:
            print("MFA not required")

        # Extract the session token from the authentication response
        session_token = response["AuthenticationResult"]["AccessToken"]

        response = cognito_client.get_user(AccessToken=session_token)
        print(response)

        return session_token
    
    except Exception as e:
        print(f"Authentication failed: {str(e)}")
        return None


def upload_to_s3(s3_auth, file_path):
    try:
        # Upload the file to S3
        s3_auth.upload_file(file_path, s3_bucket, s3_prefix + file_path)

        print(f"File {file_path} uploaded to S3.")
    except Exception as e:
        print(f"Upload to S3 failed: {str(e)}")


def main():

    # Initialize AWS Cognito and S3 clients
    cognito_client = boto3.client("cognito-idp", region_name="us-east-1")

    session_token = authenticate_user(cognito_client, username, password)

    # Use the session token to authenticate S3 uploads
    s3_auth = boto3.client("s3", aws_session_token=session_token, region_name="us-east-1")

    if s3_auth:
        file_path = "radon_results.txt"
        upload_to_s3(s3_auth, file_path)


if __name__ == "__main__":
    main()
