#!/usr/bin/env python3
"""Render the GitHub Pages status page from `evp list --json` on stdin.

Kept as a standalone script rather than an evp subcommand - this is a CI
presentation concern (what the status page looks like), not core
provisioner logic. Stdlib only, so the workflow needs no extra installs.
"""
import html
import json
import sys
from datetime import datetime, timezone

REGION = sys.argv[1] if len(sys.argv) > 1 else "eu-west-2"


def render_row(instance: dict) -> str:
    ssm_cmd = f"aws ssm start-session --target {instance['instance_id']} --region {REGION}"
    return f"""    <tr>
      <td><code>{html.escape(instance['instance_id'])}</code></td>
      <td>{html.escape(instance['instance_type'])}</td>
      <td>{html.escape(instance['owner'])}</td>
      <td>{html.escape(instance['state'])}</td>
      <td>{html.escape(instance['expires_at'] or '-')}</td>
      <td><code>{html.escape(ssm_cmd)}</code></td>
    </tr>"""


def main() -> None:
    instances = json.load(sys.stdin)
    rows = [render_row(i) for i in instances]
    table_body = "\n".join(rows) if rows else '    <tr><td colspan="6">No active instances.</td></tr>'
    generated_at = datetime.now(timezone.utc).isoformat()

    print(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Ephemeral VM Provisioner - Active Instances</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 900px;
          margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
  th, td {{ text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #ddd; }}
  th {{ color: #666; font-weight: 600; font-size: 0.85em; text-transform: uppercase; }}
  code {{ background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-size: 0.85em; }}
  footer {{ margin-top: 2rem; color: #888; font-size: 0.85em; }}
</style>
</head>
<body>
  <h1>Ephemeral VM Provisioner</h1>
  <p>Currently active instances, refreshed after every provision/reap run.</p>
  <table>
    <thead>
      <tr><th>Instance ID</th><th>Type</th><th>Owner</th><th>State</th>
          <th>Expires At (UTC)</th><th>Connect via SSM</th></tr>
    </thead>
    <tbody>
{table_body}
    </tbody>
  </table>
  <footer>Last updated: {generated_at}</footer>
</body>
</html>""")


if __name__ == "__main__":
    main()
