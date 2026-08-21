# Ephemeral VM Provisioner

Self-service, TTL-bound EC2 instances requested through a GitHub Actions
`workflow_dispatch` and automatically torn down by a scheduled reaper.
No server runs between requests, so the whole thing costs $0 on the AWS
free tier.

```
you  --workflow_dispatch-->  provision.yml            --OIDC-->  AWS  --RunInstances-->  EC2 (tagged, TTL-bound)
                              (or provision-terraform.yml)                                     |
cron (every 15 min)  ------>  reaper.yml  ----------------OIDC-->  AWS  --TerminateInstances--
```

`provision.yml` (boto3) and `provision-terraform.yml` are two independent
ways to create the *same kind* of tagged instance - pick either one. The
reaper doesn't care which path created an instance; it reads EC2 tags
directly, so both are torn down identically.

**Honest note on the Terraform path:** it's included to demonstrate IaC
fluency alongside the SDK path, not because this project's infrastructure
actually needed it. A single `aws_instance` with no security groups, load
balancers, or networking to wire together doesn't exercise what Terraform
is actually good at (dependency-graph resolution across many resource
types, long-term drift reconciliation against persisted state) - both of
which this project deliberately doesn't use anyway (see "no backend"
below). `evp` (boto3) remains the backbone: `list`/`reap`/`connect`/`history`
all depend on it, and none of them are things Terraform is well-suited to
express. Treat `infra/terraform/` as a place to try Terraform out on a
real (if simple) resource, not as evidence it was the better tool for
this particular job.

## Why it's built this way

- **GitHub Actions as the control plane.** A hosted API needs a server
  running around the clock just in case someone requests a VM. A
  `workflow_dispatch` job does the same job on demand, for free, and
  doubles as an audit log — every provision/reap is a logged run.
- **No long-lived AWS credentials.** The workflows assume an IAM role via
  OIDC federation (`aws-actions/configure-aws-credentials`), so there are
  no static access keys sitting in GitHub secrets to leak or rotate.
- **EC2 tags as the source of truth for lifecycle state.** `Owner`,
  `ExpiresAt`, and `ManagedBy` tags are what `list`/`reap` actually key
  off of - no RDS to provision or patch. A DynamoDB table exists
  alongside this, but only as a best-effort audit log; it's never read
  from, so it can't affect what gets reaped.
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
  ci.yml                  lint/type-check/test + terraform fmt/validate
  provision.yml           workflow_dispatch -> evp create (boto3 path)
  provision-terraform.yml workflow_dispatch -> terraform apply (IaC path)
  reaper.yml              cron -> evp reap (tears down either path's instances)
  publish-status-page.yml renders + deploys the GitHub Pages status page
infra/
  iam-trust-policy.json        OIDC trust policy (GitHub -> AWS)
  iam-permissions-policy.json  least-privilege EC2/IAM/DynamoDB permissions
  iam-instance-trust-policy.json  trust policy for the SSM instance role
  terraform/                   IaC alternative to the boto3 create path
scripts/
  render_status_page.py  turns `evp list --json` into the status page HTML
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

**Note on `ec2:Describe*`:** the boto3 path only ever calls a couple of
specific Describe actions, but Terraform's AWS provider (`infra/terraform/`)
calls several more during plan/refresh (instance types, security groups,
subnets, etc.). Rather than chase each one down individually, the
`DescribeAndTag` statement grants the whole `ec2:Describe*` prefix -
safe to broaden since every action in it is read-only with no mutating
blast radius, unlike `RunInstances`/`TerminateInstances`, which stay
narrowly scoped.

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

There's a second wrinkle: a job that declares `environment: name: ...`
(as `publish-status-page.yml` does, for the GitHub Pages deployment) gets
a *different* `sub` shape entirely -
`repo:OWNER@ID/REPO@ID:environment:ENV_NAME` instead of the ref-based one.
The trust policy's `sub` condition is a list covering both shapes rather
than a single string - add another entry to that list for any new
workflow that introduces its own `environment:` block.

### 3. Configure the repo

In **Settings > Secrets and variables > Actions**:

- Secret `AWS_ROLE_ARN` — the ARN of the role from step 2
- Variable `AWS_REGION` — defaults to `us-east-1` if unset

### 4. Create the SSM instance role/profile (lets you shell into a VM)

Every instance launches with this profile attached (see
`config.SSM_INSTANCE_PROFILE_NAME`), so you can connect via SSM Session
Manager instead of managing SSH keys or opening inbound ports:

```bash
aws iam create-role \
  --role-name ephemeral-vm-provisioner-instance-role \
  --assume-role-policy-document file://infra/iam-instance-trust-policy.json

aws iam attach-role-policy \
  --role-name ephemeral-vm-provisioner-instance-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

aws iam create-instance-profile \
  --instance-profile-name ephemeral-vm-provisioner-instance-profile

aws iam add-role-to-instance-profile \
  --instance-profile-name ephemeral-vm-provisioner-instance-profile \
  --role-name ephemeral-vm-provisioner-instance-role
```

The deployer role's permissions policy (`infra/iam-permissions-policy.json`)
already grants it `iam:PassRole` on this instance role, scoped to
`iam:PassedToService = ec2.amazonaws.com` - it can't pass any other role.

You'll also need the Session Manager plugin installed locally:

```bash
brew install --cask session-manager-plugin
```

### 5. Create the DynamoDB audit log table

Every `evp create` / `evp reap` writes an entry here (best-effort - a
missing table or a transient DynamoDB error never blocks the actual
provisioning or reaping). Read it back with `evp history <instance-id>` -
unlike EC2 itself, which stops returning a terminated instance after
about an hour, this table keeps the record indefinitely:

```bash
aws dynamodb create-table \
  --table-name ephemeral-vm-provisioner-audit-log \
  --attribute-definitions \
      AttributeName=instance_id,AttributeType=S \
      AttributeName=event_time,AttributeType=S \
  --key-schema \
      AttributeName=instance_id,KeyType=HASH \
      AttributeName=event_time,KeyType=RANGE \
  --provisioned-throughput ReadCapacityUnits=1,WriteCapacityUnits=1
```

Provisioned (not on-demand) capacity is used deliberately: DynamoDB's
always-free 25 RCU/WCU allowance only covers provisioned-mode tables, and
1/1 is far more than this project's write volume needs. Query an
instance's full history with:

```bash
aws dynamodb query \
  --table-name ephemeral-vm-provisioner-audit-log \
  --key-condition-expression "instance_id = :id" \
  --expression-attribute-values '{":id": {"S": "i-xxxxxxxxxxxxxxxxx"}}'
```

### 6. (Optional) Discord notifications

Both workflows post to Discord if a `DISCORD_WEBHOOK_URL` secret is set -
otherwise they skip that step silently. In Discord: **Server Settings >
Integrations > Webhooks > New Webhook**, copy its URL, then:

```bash
gh secret set DISCORD_WEBHOOK_URL --body "https://discord.com/api/webhooks/..."
```

`provision.yml` notifies on every run (success or failure). `reaper.yml`
only notifies when something was actually reaped, or on failure - not on
every empty 15-minute sweep.

### 7. Pick a free-tier AMI

Any current Amazon Linux 2023 AMI works (it ships with the SSM agent
preinstalled, so no extra setup is needed on the instance side), e.g. via
SSM:

```bash
aws ssm get-parameters --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64
```

## Usage

From GitHub: **Actions > Provision VM > Run workflow**, fill in
`instance_type` / `ttl_minutes` / `ami_id`. The instance ID and expiry
show up in the run's job summary.

**Terraform path** (see the honest note under "Why it's built this way" -
this exists to try Terraform, not because it's the better tool here):
**Actions > Provision VM (Terraform) > Run workflow** with the same
inputs - functionally identical result (same tags, same SSM profile,
torn down by the same reaper), just created via `terraform apply`
instead of a direct boto3 call. Locally:

```bash
cd infra/terraform
terraform init
terraform apply \
  -var="ami_id=ami-xxxxxxxx" \
  -var="instance_type=t3.micro" \
  -var="ttl_minutes=30" \
  -var="owner=me"
```

State is local and disposable (see `versions.tf`) - there's deliberately
no `terraform destroy` step anywhere in this project. The reaper tears
down whatever it finds tagged, regardless of which path created it, so
letting the TTL expire is always how these get cleaned up.

**Status page:** https://myeser.github.io/ephemeral-vm-provisioner/ lists
every currently-active instance and the exact `aws ssm start-session`
command to connect to it. It's a static page rendered by
`publish-status-page.yml` after every provision/reap run (via
`scripts/render_status_page.py`) - there's no server behind it, so it's
free and can't drift from what `evp list` actually reports at render time.

Locally (with AWS credentials configured):

```bash
pip install -e ".[dev]"

evp create --ami ami-xxxxxxxx --instance-type t3.micro --ttl-minutes 30 --owner me
evp list
evp reap      # normally run by the scheduled workflow, not by hand
evp terminate i-xxxxxxxxxxxxxxxxx
evp connect i-xxxxxxxxxxxxxxxxx    # SSM Session Manager shell, no SSH key needed
evp history i-xxxxxxxxxxxxxxxxx    # full create/reap timeline from DynamoDB
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
