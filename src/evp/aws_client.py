"""Thin wrapper around boto3 EC2 calls used by the provisioner.

Keeping every AWS call in one module means the CLI and the reaper logic
can be unit tested against `moto`'s mocked EC2 without ever touching a
real account, and it's the one place that needs to change if the tool
grows a second backend (e.g. GCP) later.
"""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone

import boto3

from . import config
from .models import ManagedInstance

TAG_MANAGED_BY = "ManagedBy"
TAG_EPHEMERAL = "Ephemeral"
TAG_OWNER = "Owner"
TAG_EXPIRES_AT = "ExpiresAt"
TAG_NAME = "Name"


def _client(region: str = config.DEFAULT_REGION):
    return boto3.client("ec2", region_name=region)


def _log_audit_event(
    event_type: str,
    *,
    instance_id: str,
    owner: str,
    instance_type: str,
    region: str,
    expires_at: datetime | None = None,
) -> None:
    """Best-effort write to the DynamoDB audit log.

    Never raises: a table that hasn't been created yet, or a transient
    DynamoDB error, must not stop create/reap from doing their actual
    job (launching or terminating a real, billable EC2 instance).
    """
    item = {
        "instance_id": instance_id,
        "event_time": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "owner": owner,
        "instance_type": instance_type,
        "region": region,
    }
    if expires_at is not None:
        item["expires_at"] = expires_at.isoformat()

    try:
        table = boto3.resource("dynamodb", region_name=region).Table(config.AUDIT_TABLE_NAME)
        table.put_item(Item=item)
    except Exception as exc:  # noqa: BLE001 - audit logging must never block create/reap
        print(f"warning: failed to write audit log entry for {instance_id}: {exc}", file=sys.stderr)


def create_instance(
    *,
    instance_type: str,
    ami_id: str,
    ttl_minutes: int,
    owner: str,
    region: str = config.DEFAULT_REGION,
) -> ManagedInstance:
    if instance_type not in config.ALLOWED_INSTANCE_TYPES:
        raise ValueError(
            f"instance_type {instance_type!r} is not allowed. "
            f"Allowed: {sorted(config.ALLOWED_INSTANCE_TYPES)}"
        )
    if ttl_minutes <= 0 or ttl_minutes > config.MAX_TTL_MINUTES:
        raise ValueError(
            f"ttl_minutes must be between 1 and {config.MAX_TTL_MINUTES}"
        )

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    name = f"evp-{uuid.uuid4().hex[:8]}"

    ec2 = _client(region)
    run_kwargs: dict = {
        "ImageId": ami_id,
        "InstanceType": instance_type,
        "MinCount": 1,
        "MaxCount": 1,
        "TagSpecifications": [
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": TAG_NAME, "Value": name},
                    {"Key": TAG_MANAGED_BY, "Value": config.MANAGED_BY_TAG_VALUE},
                    {"Key": TAG_EPHEMERAL, "Value": "true"},
                    {"Key": TAG_OWNER, "Value": owner},
                    {"Key": TAG_EXPIRES_AT, "Value": expires_at.isoformat()},
                ],
            }
        ],
        # Lets you shell in with `evp connect` / `aws ssm start-session`
        # instead of managing SSH keys or opening inbound ports.
        "IamInstanceProfile": {"Name": config.SSM_INSTANCE_PROFILE_NAME},
    }

    response = ec2.run_instances(**run_kwargs)
    instance = response["Instances"][0]

    _log_audit_event(
        "create",
        instance_id=instance["InstanceId"],
        owner=owner,
        instance_type=instance_type,
        region=region,
        expires_at=expires_at,
    )

    return ManagedInstance(
        instance_id=instance["InstanceId"],
        state=instance["State"]["Name"],
        instance_type=instance_type,
        owner=owner,
        launch_time=instance.get("LaunchTime"),
        expires_at=expires_at,
        public_ip=instance.get("PublicIpAddress"),
    )


def _to_managed_instance(instance: dict) -> ManagedInstance:
    tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
    expires_at_raw = tags.get(TAG_EXPIRES_AT)
    expires_at = datetime.fromisoformat(expires_at_raw) if expires_at_raw else None
    return ManagedInstance(
        instance_id=instance["InstanceId"],
        state=instance["State"]["Name"],
        instance_type=instance["InstanceType"],
        owner=tags.get(TAG_OWNER, "unknown"),
        launch_time=instance.get("LaunchTime"),
        expires_at=expires_at,
        public_ip=instance.get("PublicIpAddress"),
    )


def list_managed_instances(
    *, include_terminated: bool = False, region: str = config.DEFAULT_REGION
) -> list[ManagedInstance]:
    ec2 = _client(region)
    filters = [
        {"Name": f"tag:{TAG_MANAGED_BY}", "Values": [config.MANAGED_BY_TAG_VALUE]},
    ]
    if not include_terminated:
        filters.append(
            {
                "Name": "instance-state-name",
                "Values": ["pending", "running", "stopping", "stopped"],
            }
        )

    paginator = ec2.get_paginator("describe_instances")
    results: list[ManagedInstance] = []
    for page in paginator.paginate(Filters=filters):
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                results.append(_to_managed_instance(instance))
    return results


def terminate_instance(instance_id: str, *, region: str = config.DEFAULT_REGION) -> None:
    ec2 = _client(region)
    ec2.terminate_instances(InstanceIds=[instance_id])


def reap_expired(*, region: str = config.DEFAULT_REGION) -> list[ManagedInstance]:
    """Terminate every managed instance whose TTL has passed.

    Run on a schedule (see .github/workflows/reaper.yml) so a VM never
    outlives its TTL even if nobody tears it down by hand.
    """
    expired = [i for i in list_managed_instances(region=region) if i.is_expired]
    if expired:
        ec2 = _client(region)
        ec2.terminate_instances(InstanceIds=[i.instance_id for i in expired])
        for i in expired:
            _log_audit_event(
                "reap",
                instance_id=i.instance_id,
                owner=i.owner,
                instance_type=i.instance_type,
                region=region,
                expires_at=i.expires_at,
            )
    return expired
