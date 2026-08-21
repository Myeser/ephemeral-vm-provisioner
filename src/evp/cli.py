"""Command-line entry point for the ephemeral VM provisioner.

This is invoked directly by developers locally, and by the
provision/reaper GitHub Actions workflows in CI.
"""
from __future__ import annotations

import json

import click

from . import aws_client, config
from .models import ManagedInstance


@click.group()
def cli() -> None:
    """Create, list, and reap ephemeral EC2 instances."""


@cli.command()
@click.option("--instance-type", default="t3.micro", show_default=True)
@click.option("--ami", "ami_id", required=True, help="AMI ID to launch.")
@click.option(
    "--ttl-minutes",
    default=config.DEFAULT_TTL_MINUTES,
    show_default=True,
    type=int,
)
@click.option("--owner", required=True, help="Who requested this VM (e.g. GitHub actor).")
@click.option("--key-name", default=None, help="EC2 key pair name for SSH access.")
@click.option("--region", default=config.DEFAULT_REGION, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable output.")
def create(instance_type, ami_id, ttl_minutes, owner, key_name, region, as_json) -> None:
    """Launch a new ephemeral instance."""
    try:
        instance = aws_client.create_instance(
            instance_type=instance_type,
            ami_id=ami_id,
            ttl_minutes=ttl_minutes,
            owner=owner,
            key_name=key_name,
            region=region,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(_instance_to_dict(instance)))
    else:
        click.echo(f"Launched {instance.instance_id} ({instance.instance_type})")
        click.echo(f"  owner:      {instance.owner}")
        expires_at = instance.expires_at.isoformat() if instance.expires_at else "unknown"
        click.echo(f"  expires_at: {expires_at}")


@cli.command(name="list")
@click.option("--region", default=config.DEFAULT_REGION, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def list_(region, as_json) -> None:
    """List every instance this tool manages."""
    instances = aws_client.list_managed_instances(region=region)
    if as_json:
        click.echo(json.dumps([_instance_to_dict(i) for i in instances]))
        return
    if not instances:
        click.echo("No managed instances.")
        return
    for i in instances:
        remaining = i.minutes_remaining
        remaining_str = f"{remaining:.1f}m left" if remaining is not None else "no TTL"
        click.echo(f"{i.instance_id}  {i.state:10s}  {i.owner:15s}  {remaining_str}")


@cli.command()
@click.argument("instance_id")
@click.option("--region", default=config.DEFAULT_REGION, show_default=True)
def terminate(instance_id, region) -> None:
    """Terminate a specific instance."""
    aws_client.terminate_instance(instance_id, region=region)
    click.echo(f"Terminated {instance_id}")


@cli.command()
@click.option("--region", default=config.DEFAULT_REGION, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def reap(region, as_json) -> None:
    """Terminate every instance whose TTL has expired. Run on a schedule."""
    reaped = aws_client.reap_expired(region=region)
    if as_json:
        click.echo(json.dumps([_instance_to_dict(i) for i in reaped]))
        return
    if not reaped:
        click.echo("Nothing to reap.")
        return
    for i in reaped:
        overdue = abs(i.minutes_remaining) if i.minutes_remaining is not None else 0
        click.echo(f"Reaped {i.instance_id} (owner={i.owner}, expired {overdue:.1f}m ago)")


def _instance_to_dict(instance: ManagedInstance) -> dict:
    return {
        "instance_id": instance.instance_id,
        "state": instance.state,
        "instance_type": instance.instance_type,
        "owner": instance.owner,
        "expires_at": instance.expires_at.isoformat() if instance.expires_at else None,
        "public_ip": instance.public_ip,
    }


def main() -> None:
    cli(prog_name="evp")


if __name__ == "__main__":
    main()
