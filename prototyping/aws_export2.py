import boto3
from botocore.exceptions import NoCredentialsError

# from botocore import S3Object

# https://www.archerimagine.com/articles/aws/aws-cognito-tutorials.html

# AWS S3 Bucket Details
# client_id="46ugbt3jat1spc70ulio46btmc"
# s3_bucket="amplify-datauploader-prodmi-stagingbucketeec2e4de-x4qrvyzen65z"
# s3_prefix="private/"
# username="anonymizer"
# password="P^l-8n+(ha?$6*&3"
account_id = "691746062725"  # RSNA AWS account id (covid-image AWS account)
region_name = "us-east-1"  # AWS region
app_client_id = "fgnijvmig42ruvn37mte1p9au"  # cognito application client id ("Anonymizer-2")
user_pool_id = "us-east-1_cFn3IKLqG"  # cognito user pool for "Anonymizer-2"
identity_pool_id = "us-east-1:3c616c9d-58f0-4c89-a412-ea8cf259039a"  # cognito identity pool
s3_bucket_name = "amplify-datauploader-prodmi-stagingbucketeec2e4de-x4qrvyzen65z"
s3_prefix = "private2"
username = "anonymizer2"  # "johndoe1"
password = "SpeedFast1967#"  # "SpeedFast1967$"
# - At least 12 characters
# - At least one uppercase letter
# - At least one lowercase letter
# - At least one number
# - At least one special character


def authenticate_user():
    # Authenticate the user against the Cognito User Pool
    cognito_idp_client = boto3.client("cognito-idp", region_name=region_name)

    # Cognito App Sign in with the provided credentials
    response = cognito_idp_client.initiate_auth(
        ClientId=app_client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": username,
            "PASSWORD": password,
        },
    )
    print(response)

    if "ChallengeName" in response and response["ChallengeName"] == "NEW_PASSWORD_REQUIRED":
        # New password required:
        session = response["Session"]
        new_password = "SpeedFast1967#"
        response = cognito_idp_client.respond_to_auth_challenge(
            ClientId=app_client_id,
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

    response = cognito_idp_client.get_user(AccessToken=session_token)
    print(response)

    # Use the Cognito Identity Token to obtain temporary credentials from the Cognito Identity Pool

    # Assume the IAM role associated with the Cognito Identity Pool
    cognito_identity_client = boto3.client("cognito-identity", region_name=region_name)
    response = cognito_identity_client.get_id(
        IdentityPoolId=identity_pool_id,
        AccountId=account_id,
        Logins={f"cognito-idp.{region_name}.amazonaws.com/{user_pool_id}": cognito_identity_token},
    )

    print(response)

    identity_id = response["IdentityId"]

    # Get temporary AWS credentials
    credentials = cognito_identity_client.get_credentials_for_identity(
        IdentityId=identity_id,
        Logins={f"cognito-idp.{region_name}.amazonaws.com/{user_pool_id}": cognito_identity_token},
    )

    print(credentials)

    return credentials


def main():
    print("AWS S3 File Upload Example")

    try:
        # Authenticate the user and obtain temporary credentials
        credentials = authenticate_user()

        # Use the temporary credentials with Boto3 for S3 operations
        s3 = boto3.client(
            "s3",
            aws_access_key_id=credentials["Credentials"]["AccessKeyId"],
            aws_secret_access_key=credentials["Credentials"]["SecretKey"],
            aws_session_token=credentials["Credentials"]["SessionToken"],
        )

        # Now you can make S3 requests using the configured credentials
        # response = s3.list_buckets()
        # print(response)

        # Example: Upload two files to S3
        file_path_1 = "/Users/administrator/Desktop/aws_test_upload_1.dcm"
        object_key = f"{s3_prefix}/1/aws_test_upload_1.dcm"

        s3.upload_file(file_path_1, s3_bucket_name, object_key)
        print(f"File 1 uploaded successfully to s3://{s3_bucket_name}/{object_key}")

        file_path_2 = "/Users/administrator/Desktop/aws_test_upload_2.dcm"
        object_key = f"{s3_prefix}/2/aws_test_upload_2.dcm"

        s3.upload_file(file_path_2, s3_bucket_name, object_key)
        print(f"File 2 uploaded successfully to s3://{s3_bucket_name}/{object_key}")

        response = s3.list_objects(Bucket=s3_bucket_name, Prefix=s3_prefix)
        if "Contents" in response:
            for obj in response["Contents"]:
                print(obj["Key"])
        else:
            print("No objects found in the bucket.")

    except NoCredentialsError:
        print("Error: AWS credentials not available.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
