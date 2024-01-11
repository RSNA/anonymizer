import boto3
from botocore.exceptions import NoCredentialsError

# https://www.archerimagine.com/articles/aws/aws-cognito-tutorials.html

# AWS S3 Bucket Details
# client_id="46ugbt3jat1spc70ulio46btmc"
# s3_bucket="amplify-datauploader-prodmi-stagingbucketeec2e4de-x4qrvyzen65z"
# s3_prefix="private/"
# username="anonymizer"
# password="P^l-8n+(ha?$6*&3"
user_pool_id = "us-east-1_cFn3IKLqG"
identity_pool_id = "us-east-1:3c616c9d-58f0-4c89-a412-ea8cf259039a"
region_name = "us-east-1"
client_id = "fgnijvmig42ruvn37mte1p9au"
s3_bucket_name = "amplify-datauploader-prodmi-stagingbucketeec2e4de-x4qrvyzen65z"
s3_prefix = "private"
username = "anonymizer2"
password = "SpeedFast1967#"
# - At least 12 characters
# - At least one uppercase letter
# - At least one lowercase letter
# - At least one number
# - At least one special character


def authenticate_user(username, password, user_pool_id, client_id, identity_pool_id):
    # Authenticate the user against the Cognito User Pool
    cognito_client = boto3.client("cognito-idp", region_name=region_name)
    # Sign in with the provided credentials
    response = cognito_client.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": username,
            "PASSWORD": password,
        },
    )
    print(response)

    if (
        "ChallengeName" in response
        and response["ChallengeName"] == "NEW_PASSWORD_REQUIRED"
    ):
        # New password required:
        session = response["Session"]
        new_password = "SpeedFast1967#"
        response = cognito_client.respond_to_auth_challenge(
            ClientId=client_id,
            ChallengeName="NEW_PASSWORD_REQUIRED",
            ChallengeResponses={
                "USERNAME": username,
                "NEW_PASSWORD": new_password,
            },
            Session=session,
        )
        print(response)

    else:
        print("No ChallengeName in response.")

    # Extract the session token from the authentication response
    session_token = response["AuthenticationResult"][
        "AccessToken"
    ]  # value of AccessToken from cognito-idp.initiate_auth
    cognito_identity_token = response["AuthenticationResult"][
        "IdToken"
    ]  # value of AccessToken from cognito-idp.initiate_auth

    response = cognito_client.get_user(AccessToken=session_token)
    print(response)

    # Use the Cognito Identity Token to obtain temporary credentials from the Cognito Identity Pool
    credentials = get_temporary_credentials(cognito_identity_token, identity_pool_id)

    return credentials


def get_temporary_credentials(cognito_identity_token, identity_pool_id):
    # Assume the IAM role associated with the Cognito Identity Pool
    cognito = boto3.client("cognito-identity", region_name=region_name)
    response = cognito.get_id(
        IdentityPoolId=identity_pool_id,
    )

    identity_id = response["IdentityId"]

    # Get temporary AWS credentials
    credentials = cognito.get_credentials_for_identity(
        IdentityId=identity_id,
        Logins={
            f"cognito-idp.{region_name}.amazonaws.com/{user_pool_id}": cognito_identity_token
        },
    )

    return credentials


def main():
    try:
        # Authenticate the user and obtain temporary credentials
        credentials = authenticate_user(
            username, password, user_pool_id, client_id, identity_pool_id
        )

        # Use the temporary credentials with Boto3 for S3 operations
        s3 = boto3.client(
            "s3",
            aws_access_key_id=credentials["Credentials"]["AccessKeyId"],
            aws_secret_access_key=credentials["Credentials"]["SecretKey"],
            aws_session_token=credentials["Credentials"]["SessionToken"],
        )

        # Now you can make S3 requests using the configured credentials

        # Example: Upload a file to S3
        file_path = "/Users/michaelevans/Desktop/2023_Kaggle_AI_Report.pdf"
        object_key = f"{s3_prefix}/2023_Kaggle_AI_Report.pdf"

        s3.upload_file(file_path, s3_bucket_name, object_key)
        print(f"File uploaded successfully to s3://{s3_bucket_name}/{object_key}")

    except NoCredentialsError:
        print("Error: AWS credentials not available.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
