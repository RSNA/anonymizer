import boto3
from botocore.exceptions import NoCredentialsError
from pprint import pprint

# RSNA Anonymizer UPLOAD AWS S3 Bucket Details
# account_id = "691746062725"  # RSNA AWS account id (covid-image AWS account)
# region_name = "us-east-1"  # AWS region
# app_client_id = "fgnijvmig42ruvn37mte1p9au"  # cognito application client id ("Anonymizer-2")
# user_pool_id = "us-east-1_cFn3IKLqG"  # cognito user pool for "Anonymizer-2"
# identity_pool_id = "us-east-1:3c616c9d-58f0-4c89-a412-ea8cf259039a"  # cognito identity pool
s3_bucket_name = "storage.midrc"  # "amplify-datauploader-prodmi-stagingbucketeec2e4de-x4qrvyzen65z"
s3_prefix = "rsna_curation_test"
aws_tag = ""
# username = "anonymizer2"
# password = "*************"
# - At least 12 characters
# - At least one uppercase letter
# - At least one lowercase letter
# - At least one number
# - At least one special character

# RCLONE
# rclone mount storage.midrc:storage.midrc X: --vfs-cache-mode=full


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
    # print(response)

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
    # print(response)
    global aws_tag
    aws_tag = response["UserAttributes"][0]["Value"]
    print(f"User specfic upload tag: {aws_tag}")

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

    # print(credentials)
    print(f"Temporary credentials obtained successfully for {username}")
    return credentials


def main():
    print("AWS S3 File Import Example")

    try:
        # Authenticate the user and obtain temporary credentials
        # credentials = authenticate_user()

        # Use the temporary credentials with Boto3 for S3 operations
        s3 = boto3.client(
            "s3",
            # aws_access_key_id=credentials["Credentials"]["AccessKeyId"],
            # aws_secret_access_key=credentials["Credentials"]["SecretKey"],
            # aws_session_token=credentials["Credentials"]["SessionToken"],
        )

        # Now you can make S3 requests using the configured credentials
        response = s3.list_buckets()
        pprint(response)

        prefix = f"{s3_prefix}/"
        response = s3.list_objects(Bucket=s3_bucket_name, Prefix=prefix)
        obj_keys = []
        if "Contents" in response:
            for obj in response["Contents"]:
                print(obj["Key"])
                obj_keys.append(obj["Key"])
        else:
            print("No objects found in the bucket.")

        if obj_keys:
            s3.download_file(s3_bucket_name, obj_keys[1], "test_download.dcm")

    except NoCredentialsError:
        print("Error: AWS credentials not available.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
