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
