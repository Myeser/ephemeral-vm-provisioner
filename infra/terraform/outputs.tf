output "instance_id" {
  value = aws_instance.this.id
}

output "instance_type" {
  value = aws_instance.this.instance_type
}

output "owner" {
  value = var.owner
}

output "expires_at" {
  value = local.expires_at
}

output "public_ip" {
  value = aws_instance.this.public_ip
}
