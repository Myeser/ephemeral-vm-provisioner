"""Shared moto setup helpers used by both test_aws_client and test_cli."""
import json

import boto3

from evp import config

_INSTANCE_ROLE_TRUST_POLICY = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
)


def create_mock_instance_profile(region: str) -> None:
    """Create the SSM instance profile in moto's mocked IAM.

    `create_instance` attaches this profile to every launched instance
    (see aws_client.py), and moto's EC2 mock validates that it actually
    exists - real AWS would reject RunInstances otherwise too.
    """
    iam = boto3.client("iam", region_name=region)
    iam.create_role(
        RoleName="test-instance-role",
        AssumeRolePolicyDocument=_INSTANCE_ROLE_TRUST_POLICY,
    )
    iam.create_instance_profile(InstanceProfileName=config.SSM_INSTANCE_PROFILE_NAME)
    iam.add_role_to_instance_profile(
        InstanceProfileName=config.SSM_INSTANCE_PROFILE_NAME,
        RoleName="test-instance-role",
    )


def create_mock_audit_table(region: str) -> None:
    """Create the audit log table in moto's mocked DynamoDB.

    Without this, `_log_audit_event` silently swallows a
    ResourceNotFoundException (by design - see aws_client.py), so tests
    that want to assert on audit entries need the table to actually exist.
    """
    dynamodb = boto3.client("dynamodb", region_name=region)
    dynamodb.create_table(
        TableName=config.AUDIT_TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "instance_id", "AttributeType": "S"},
            {"AttributeName": "event_time", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "instance_id", "KeyType": "HASH"},
            {"AttributeName": "event_time", "KeyType": "RANGE"},
        ],
        ProvisionedThroughput={"ReadCapacityUnits": 1, "WriteCapacityUnits": 1},
    )
