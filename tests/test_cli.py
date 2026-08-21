"""Tests for the click CLI, exercised via CliRunner against moto."""
import json

import boto3
from click.testing import CliRunner
from moto import mock_aws

from evp.cli import cli

from .aws_fixtures import create_mock_audit_table, create_mock_instance_profile

REGION = "eu-west-2"


def _default_ami(ec2_client) -> str:
    return ec2_client.describe_images(Owners=["amazon"])["Images"][0]["ImageId"]


def test_create_and_list_round_trip():
    runner = CliRunner()
    with mock_aws():
        create_mock_instance_profile(REGION)
        create_mock_audit_table(REGION)
        ec2_client = boto3.client("ec2", region_name=REGION)
        ami_id = _default_ami(ec2_client)

        create_result = runner.invoke(
            cli,
            [
                "create",
                "--instance-type", "t3.micro",
                "--ami", ami_id,
                "--ttl-minutes", "30",
                "--owner", "octocat",
                "--region", REGION,
                "--json",
            ],
        )
        assert create_result.exit_code == 0, create_result.output
        created = json.loads(create_result.output)
        assert created["owner"] == "octocat"

        list_result = runner.invoke(cli, ["list", "--region", REGION, "--json"])
        assert list_result.exit_code == 0, list_result.output
        listed = json.loads(list_result.output)
        assert len(listed) == 1
        assert listed[0]["instance_id"] == created["instance_id"]


def test_create_rejects_bad_instance_type():
    runner = CliRunner()
    with mock_aws():
        create_mock_instance_profile(REGION)
        create_mock_audit_table(REGION)
        ec2_client = boto3.client("ec2", region_name=REGION)
        ami_id = _default_ami(ec2_client)

        result = runner.invoke(
            cli,
            [
                "create",
                "--instance-type", "m5.24xlarge",
                "--ami", ami_id,
                "--owner", "octocat",
                "--region", REGION,
            ],
        )
        assert result.exit_code != 0
        assert "not allowed" in result.output
