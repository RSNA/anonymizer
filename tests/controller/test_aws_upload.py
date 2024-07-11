from dotenv import load_dotenv
import os
from pathlib import Path
from botocore.exceptions import NoCredentialsError
from src.controller.project import ProjectController
from pydicom.data import get_testdata_file

from tests.controller.dicom_test_files import ct_small_filename

# Load environment variables from .env file (for username/password for AWS upload)
load_dotenv()


def test_send_1_dicomfile_to_AWS_S3_and_list_objects(temp_dir: str, controller: ProjectController):

    dcm_file_path = str(get_testdata_file(ct_small_filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    username = os.getenv("AWS_USERNAME")
    pw = os.getenv("AWS_PASSWORD")
    
    assert username
    assert pw

    controller.model.aws_cognito.username = username
    controller.model.aws_cognito.password = pw

    s3 = controller.AWS_authenticate()
    assert s3

    try:
        assert controller._aws_user_directory

        object_key: str = Path(
            controller.model.aws_cognito.s3_prefix,
            controller._aws_user_directory,
            controller.model.project_name,
            f"{ct_small_filename}",
        ).as_posix()

        s3.upload_file(dcm_file_path, controller.model.aws_cognito.s3_bucket, object_key)

    except NoCredentialsError:
        assert False

    except Exception as e:
        assert False

    # Ensure cached credentials are returned from next call to AWS_authenticate()
    s3_b = controller.AWS_authenticate()
    assert s3_b == s3

    # List the objects in the bucket at the prefix to ensure the file was uploaded
    aws_project_prefix: str = Path(
        controller.model.aws_cognito.s3_prefix, controller._aws_user_directory, controller.model.project_name
    ).as_posix()

    response = s3.list_objects(Bucket=controller.model.aws_cognito.s3_bucket, Prefix=aws_project_prefix)

    assert "Contents" in response

    aws_files = [obj["Key"] for obj in response["Contents"]]

    assert object_key in aws_files

    # Test ListObjectsV2 paginator
    paginator = s3.get_paginator("list_objects_v2")
    filenames = []

    # Initial request with prefix (if provided)
    pagination_config = {"Bucket": controller.model.aws_cognito.s3_bucket, "Prefix": aws_project_prefix}
    for page in paginator.paginate(**pagination_config):
        if "Contents" in page:
            filenames.extend([os.path.basename(obj["Key"]) for obj in page["Contents"]])

    assert ct_small_filename in filenames
