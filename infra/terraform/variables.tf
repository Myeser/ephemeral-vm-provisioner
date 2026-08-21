variable "region" {
  description = "AWS region to launch in."
  type        = string
  default     = "eu-west-2"
}

variable "ami_id" {
  description = "AMI ID to launch."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type."
  type        = string
  default     = "t3.micro"

  validation {
    condition     = contains(["t2.micro", "t3.micro"], var.instance_type)
    error_message = "instance_type must be one of: t2.micro, t3.micro (same limit as the boto3 path - see config.ALLOWED_INSTANCE_TYPES)."
  }
}

variable "ttl_minutes" {
  description = "Minutes until the reaper is allowed to terminate this instance."
  type        = number
  default     = 60

  validation {
    condition     = var.ttl_minutes > 0 && var.ttl_minutes <= 240
    error_message = "ttl_minutes must be between 1 and 240 (same limit as config.MAX_TTL_MINUTES)."
  }
}

variable "owner" {
  description = "Who requested this VM (e.g. GitHub actor)."
  type        = string
}

variable "instance_profile_name" {
  description = "Name of the pre-created SSM instance profile (see infra/iam-instance-trust-policy.json)."
  type        = string
  default     = "ephemeral-vm-provisioner-instance-profile"
}
