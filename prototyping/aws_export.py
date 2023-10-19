import boto3
from getpass import getpass

# https://www.archerimagine.com/articles/aws/aws-cognito-tutorials.html

# AWS Cognito Client ID
client_id = "your-client-id"

# AWS S3 Bucket Details
s3_bucket = "your-s3-bucket"
s3_prefix = "uploads/"  # Optional: You can specify a prefix within the bucket

# Initialize AWS Cognito and S3 clients
cognito_client = boto3.client("cognito-idp", region_name="us-east-1")
s3_client = boto3.client("s3")


def authenticate_user(username, password):
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

        # Extract the session token from the authentication response
        session_token = response["AuthenticationResult"]["AccessToken"]

        # Use the session token to authenticate S3 uploads
        s3 = boto3.client("s3", aws_session_token=session_token)

        return s3
    except Exception as e:
        print(f"Authentication failed: {str(e)}")
        return None


def upload_to_s3(s3, file_path):
    try:
        # Upload the file to S3
        s3.upload_file(file_path, s3_bucket, s3_prefix + file_path)

        print(f"File {file_path} uploaded to S3.")
    except Exception as e:
        print(f"Upload to S3 failed: {str(e)}")


def main():
    username = input("Username: ")
    password = getpass("Password: ")

    s3 = authenticate_user(username, password)

    if s3:
        file_path = "path_to_your_local_file.txt"
        upload_to_s3(s3, file_path)


if __name__ == "__main__":
    main()
