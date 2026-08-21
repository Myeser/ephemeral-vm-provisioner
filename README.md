# Ephemeral VM Provisioner

Self-service, TTL-bound EC2 instances requested through a GitHub Actions
`workflow_dispatch` and automatically torn down by a scheduled reaper.
No server runs between requests, so the whole thing costs $0 on the AWS
free tier.

```
you  --workflow_dispatch-->  provision.yml  --OIDC-->  AWS  --RunInstances-->  EC2 (tagged, TTL-bound)
                                                                                     |
cron (every 15 min)  ------>  reaper.yml  ----OIDC---->  AWS  --TerminateInstances--
```

## Why it's built this way

- **GitHub Actions as the control plane.** A hosted API needs a server
  running around the clock just in case someone requests a VM. A
  `workflow_dispatch` job does the same job on demand, for free, and
  doubles as an audit log — every provision/reap is a logged run.
- **No long-lived AWS credentials.** The workflows assume an IAM role via
  OIDC federation (`aws-actions/configure-aws-credentials`), so there are
  no static access keys sitting in GitHub secrets to leak or rotate.
- **EC2 tags as the database.** `Owner`, `ExpiresAt`, and `ManagedBy` tags
  are the single source of truth for what this tool owns. No RDS/DynamoDB
  to provision, patch, or pay for.
- **The reaper is the safety net.** TTL enforcement doesn't rely on the
  requester behaving — `reaper.yml` terminates anything past its
  `ExpiresAt` tag every 15 minutes, and `evp create` refuses TTLs beyond
  `MAX_TTL_MINUTES` up front (see `src/evp/config.py`).

## Project layout

```
src/evp/
  cli.py          click CLI: create / list / terminate / reap
  aws_client.py   all boto3 EC2 calls, tagging scheme
  models.py       ManagedInstance dataclass (TTL/expiry logic)
  config.py       safety limits (allowed instance types, max TTL)
tests/            pytest + moto, no real AWS calls
.github/workflows/
  ci.yml          lint (ruff) + type-check (mypy) + test on every push
  provision.yml   workflow_dispatch -> evp create
  reaper.yml      cron -> evp reap
infra/
  iam-trust-policy.json        OIDC trust policy (GitHub -> AWS)
  iam-permissions-policy.json  least-privilege EC2 permissions
```

## Setup

### 1. Create the GitHub OIDC identity provider in AWS (one-time per account)

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### 2. Create the IAM role

The repo/org placeholder is already filled in. Replace `<ACCOUNT_ID>` in
`infra/iam-trust-policy.json` with your AWS account ID
(`aws sts get-caller-identity --query Account --output text`), then:

```bash
aws iam create-role \
  --role-name ephemeral-vm-provisioner \
  --assume-role-policy-document file://infra/iam-trust-policy.json

aws iam put-role-policy \
  --role-name ephemeral-vm-provisioner \
  --policy-name ephemeral-vm-provisioner-permissions \
  --policy-document file://infra/iam-permissions-policy.json
```

**Note on the `sub` claim:** GitHub embeds immutable owner/repo IDs directly
into the OIDC token's `sub` claim (`repo:OWNER@OWNER_ID/REPO@REPO_ID:ref:...`),
not just the plain `OWNER/REPO` name — this stops a deleted-and-recreated or
renamed repo from inheriting another repo's trust. AWS also requires the
trust policy's condition to reference `sub` or `job_workflow_ref` explicitly
(a plain `repository`/`ref` condition is rejected as too permissive for a
public OIDC provider). If you fork or rename this repo, get the real value
by temporarily adding a step to a workflow that prints the decoded token
(see git history for `provision.yml` around the initial setup) and update
`infra/iam-trust-policy.json` + `aws iam update-assume-role-policy`
accordingly.

### 3. Configure the repo

In **Settings > Secrets and variables > Actions**:

- Secret `AWS_ROLE_ARN` — the ARN of the role from step 2
- Variable `AWS_REGION` — defaults to `us-east-1` if unset

### 4. Pick a free-tier AMI

Any current Amazon Linux 2023 AMI works, e.g. via SSM:

```bash
aws ssm get-parameters --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64
```

## Usage

From GitHub: **Actions > Provision VM > Run workflow**, fill in
`instance_type` / `ttl_minutes` / `ami_id`. The instance ID and expiry
show up in the run's job summary.

Locally (with AWS credentials configured):

```bash
pip install -e ".[dev]"

evp create --ami ami-xxxxxxxx --instance-type t3.micro --ttl-minutes 30 --owner me
evp list
evp reap      # normally run by the scheduled workflow, not by hand
evp terminate i-xxxxxxxxxxxxxxxxx
```

## Security model

- **Pull requests can't reach AWS.** `provision.yml` and `reaper.yml`
  only trigger on `workflow_dispatch` / `schedule`, never `pull_request`
  — GitHub does not fire those from a PR, and `workflow_dispatch` also
  requires the invoker to already have write access to the repo. The
  only workflow that runs on `pull_request` (including from forks) is
  `ci.yml`, which never requests `id-token`/AWS credentials and tests
  entirely against `moto`'s mocked EC2.
- **The OIDC trust policy is scoped to `main`.** `infra/iam-trust-policy.json`'s
  `sub` condition is `repo:<org>/<repo>:ref:refs/heads/main`, so even a
  manual `workflow_dispatch` run against a branch with an edited,
  unmerged workflow file cannot assume the AWS role — only runs against
  the reviewed `main` branch can.
- **Never add `pull_request_target`** to any workflow in this repo. It
  runs with the base repo's secrets even for fork PRs, which is the
  classic way this kind of pipeline gets abused. Both AWS-touching
  workflows have an inline comment warning against it.

## Safety limits

- Only `t2.micro` / `t3.micro` can be launched (`config.ALLOWED_INSTANCE_TYPES`)
- TTL is capped at `config.MAX_TTL_MINUTES` (default 240)
- The reaper can only terminate instances tagged
  `ManagedBy=ephemeral-vm-provisioner` — it will never touch anything
  else in the account (enforced by both the code and the IAM policy)

## Testing

```bash
pip install -e ".[dev]"
ruff check .
mypy src
pytest -v
```

All AWS calls are mocked with `moto`, so the test suite needs no real
AWS credentials and never touches a live account.

## Roadmap

- [ ] Slack/Discord notification on provision + reap
- [ ] DynamoDB audit log of every provision/destroy event
- [ ] Static status page (GitHub Pages) listing currently-active VMs
- [ ] Terraform module as an alternative to the boto3 path
