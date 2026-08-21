"""Configuration constants for the ephemeral VM provisioner.

Keeping the safety limits here (rather than only relying on IAM) means
`evp create` fails fast and loudly instead of surfacing an opaque
AWS `AccessDenied` when someone tries to launch something too big or
too long-lived.
"""
import os

ALLOWED_INSTANCE_TYPES = {"t2.micro", "t3.micro"}
MAX_TTL_MINUTES = 240
DEFAULT_TTL_MINUTES = 60
MANAGED_BY_TAG_VALUE = "ephemeral-vm-provisioner"
DEFAULT_REGION = os.environ.get("AWS_REGION", "eu-west-2")

# Instance profile attached at launch so you can shell in via SSM Session
# Manager instead of managing SSH keys / open inbound ports. See
# infra/iam-instance-trust-policy.json for the role it wraps.
SSM_INSTANCE_PROFILE_NAME = "ephemeral-vm-provisioner-instance-profile"

# DynamoDB table recording every create/reap event. Writes are
# best-effort (see aws_client._log_audit_event) - a table that doesn't
# exist yet, or a transient DynamoDB error, must never block create or
# reap themselves.
AUDIT_TABLE_NAME = "ephemeral-vm-provisioner-audit-log"
