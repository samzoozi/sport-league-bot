import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ["TABLE_NAME"] = "test-table"
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3
import pytest
from moto import mock_aws

from bot import db as db_module


@pytest.fixture(autouse=True)
def dynamodb_table():
    with mock_aws():
        db_module._resource = None
        db_module._low_level_client = None

        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-table",
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield

        db_module._resource = None
        db_module._low_level_client = None
