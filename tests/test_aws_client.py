"""Unit tests for aws_client, run entirely against moto's mocked EC2."""
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws

from evp import aws_client, config

REGION = "eu-west-2"


def _default_ami(ec2_client) -> str:
    images = ec2_client.describe_images(Owners=["amazon"])["Images"]
    return images[0]["ImageId"]


@pytest.fixture
def ec2_client():
    with mock_aws():
        yield boto3.client("ec2", region_name=REGION)


def test_create_instance_tags_and_returns_expiry(ec2_client):
    ami_id = _default_ami(ec2_client)

    instance = aws_client.create_instance(
        instance_type="t3.micro",
        ami_id=ami_id,
        ttl_minutes=30,
        owner="octocat",
        region=REGION,
    )

    assert instance.state in {"pending", "running"}
    assert instance.owner == "octocat"
    assert instance.expires_at > datetime.now(timezone.utc)


def test_create_instance_rejects_disallowed_instance_type(ec2_client):
    ami_id = _default_ami(ec2_client)
    with pytest.raises(ValueError, match="not allowed"):
        aws_client.create_instance(
            instance_type="m5.24xlarge",
            ami_id=ami_id,
            ttl_minutes=30,
            owner="octocat",
            region=REGION,
        )


def test_create_instance_rejects_ttl_over_max(ec2_client):
    ami_id = _default_ami(ec2_client)
    with pytest.raises(ValueError, match="ttl_minutes"):
        aws_client.create_instance(
            instance_type="t3.micro",
            ami_id=ami_id,
            ttl_minutes=config.MAX_TTL_MINUTES + 1,
            owner="octocat",
            region=REGION,
        )


def test_list_managed_instances_only_returns_tagged_ones(ec2_client):
    ami_id = _default_ami(ec2_client)
    aws_client.create_instance(
        instance_type="t3.micro", ami_id=ami_id, ttl_minutes=30, owner="octocat", region=REGION
    )
    # An instance launched outside the tool shouldn't show up.
    ec2_client.run_instances(ImageId=ami_id, InstanceType="t3.micro", MinCount=1, MaxCount=1)

    managed = aws_client.list_managed_instances(region=REGION)

    assert len(managed) == 1
    assert managed[0].owner == "octocat"


def test_reap_expired_terminates_only_expired_instances(ec2_client):
    ami_id = _default_ami(ec2_client)
    fresh = aws_client.create_instance(
        instance_type="t3.micro", ami_id=ami_id, ttl_minutes=60, owner="octocat", region=REGION
    )
    stale = aws_client.create_instance(
        instance_type="t3.micro", ami_id=ami_id, ttl_minutes=60, owner="octocat", region=REGION
    )
    # Force the second instance's tag into the past to simulate expiry.
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    ec2_client.create_tags(
        Resources=[stale.instance_id], Tags=[{"Key": "ExpiresAt", "Value": past}]
    )

    reaped = aws_client.reap_expired(region=REGION)

    assert [i.instance_id for i in reaped] == [stale.instance_id]

    remaining = {
        i.instance_id: i.state
        for i in aws_client.list_managed_instances(include_terminated=True, region=REGION)
    }
    assert remaining[stale.instance_id] == "terminated"
    assert remaining[fresh.instance_id] in {"pending", "running"}
