terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # No backend block on purpose - state stays local to whichever run
  # applies this (a GitHub Actions job, or your laptop) and is never
  # persisted or reused. That's deliberate, not an oversight: the
  # tag-based reaper (see src/evp/aws_client.py) tears down every
  # instance it manages by reading EC2 tags directly, regardless of
  # whether boto3 or Terraform created it - so nothing here ever needs
  # to run `terraform destroy` against old state. Adding a remote
  # backend (S3 + a lock table) would only add cost and complexity this
  # project doesn't need.
}

provider "aws" {
  region = var.region
}
