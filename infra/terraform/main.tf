locals {
  managed_by_tag_value = "ephemeral-vm-provisioner"
  expires_at           = timeadd(timestamp(), "${var.ttl_minutes}m")
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_instance" "this" {
  ami           = var.ami_id
  instance_type = var.instance_type

  # Same access model as the boto3 path: no SSH key, shell in via SSM
  # Session Manager instead (see README "Create the SSM instance
  # role/profile"). This profile must already exist in the account.
  iam_instance_profile = var.instance_profile_name

  tags = {
    Name      = "evp-tf-${random_id.suffix.hex}"
    ManagedBy = local.managed_by_tag_value
    Ephemeral = "true"
    Owner     = var.owner
    ExpiresAt = local.expires_at
  }

  lifecycle {
    # `timestamp()` changes on every plan, which would otherwise make
    # Terraform think ExpiresAt needs updating on every subsequent
    # apply against this same state. Since this module is only ever
    # applied once per instance (see versions.tf on state), that
    # never actually happens in practice, but ignoring it here is the
    # correct declaration of intent regardless.
    ignore_changes = [tags["ExpiresAt"]]
  }
}
