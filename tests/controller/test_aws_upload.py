import os
import boto3
from botocore.exceptions import NoCredentialsError
from controller.project import ProjectController
from pydicom.data import get_testdata_file

from tests.controller.dicom_test_files import ct_small_filename


def test_send_1_dicomfile_to_AWS_S3(temp_dir: str, controller: ProjectController):

    dcm_file_path = str(get_testdata_file(ct_small_filename))
    assert dcm_file_path
    assert os.path.exists(dcm_file_path)

    credentials = controller.AWS_authenticate()
    assert credentials
    assert type(credentials) == dict
    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=credentials["Credentials"]["AccessKeyId"],
            aws_secret_access_key=credentials["Credentials"]["SecretKey"],
            aws_session_token=credentials["Credentials"]["SessionToken"],
        )

        object_key = f"unit_test/{ct_small_filename}"
        s3.upload_file(dcm_file_path, controller.model.aws_cognito.s3_bucket, object_key)

    except NoCredentialsError:
        assert False

    except Exception as e:
        assert False

    # Ensure cached credentials are returned from next call to AWS_authenticate()
    credentials2 = controller.AWS_authenticate()
    assert credentials2 == credentials
