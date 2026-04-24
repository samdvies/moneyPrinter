# AWS eu-west-1 deployment (EC2 + Docker Compose)

Producer-only artifacts: this directory does not deploy infrastructure by itself. An operator with AWS credentials runs `provision.sh` from a laptop, then SSHs in to configure secrets and start the stack.

## Prerequisites

- AWS CLI v2 configured with credentials that can create EC2, Elastic IPs, and security groups in `eu-west-1`.
- Your home (or office) public IPv4 in CIDR form, e.g. `203.0.113.10/32`, for SSH ingress.
- An EC2 key pair named `algo-betting` (or override `KEY_NAME`) already imported or created in the target account/region.
- Local SSH client and private key matching the key pair.

## Provision EC2 (one-liner)

From the **repository root**:

```bash
KEY_NAME=algo-betting HOME_CIDR=203.0.113.10/32 ./deploy/provision.sh
```

The script is idempotent: it reuses an existing security group and, if an instance tagged `algo-betting-primary` already exists, prints its public IP instead of launching a duplicate.

## SSH

```bash
ssh -i ~/.ssh/algo-betting.pem ec2-user@<elastic-ip>
```

## Configure production env

On the host (after `git clone` from `bootstrap.sh`):

```bash
cd /opt/algo-betting
cp deploy/.env.prod.template deploy/.env.prod
# Edit deploy/.env.prod — set POSTGRES_PASSWORD and any other vars.
sudo systemctl start algo-betting
```

`deploy/.env.prod` is gitignored locally; only `deploy/.env.prod.template` is tracked in git.

## Logs

```bash
cd /opt/algo-betting
sudo docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod logs -f ingestion
```

## Database migrations

After Postgres is up:

```bash
sudo docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod exec ingestion \
  uv run python -m scripts.migrate
```

## Seed Polymarket strategy row

```bash
sudo docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod exec strategy_runner \
  uv run python -m scripts.seed_polymarket_strategy
```

## Tear down

```bash
sudo systemctl stop algo-betting
# On your laptop, terminate the instance (replace i-xxxxxxxx):
aws ec2 terminate-instances --region eu-west-1 --instance-ids i-xxxxxxxx
```

Release the Elastic IP in the EC2 console if you no longer need it.

## Cost estimate (operator budget)

- **t4g.small** on-demand in eu-west-1: roughly **£12/month** (varies with spot/on-demand and GBP/USD).
- **30 GB gp3** root volume: roughly **£2/month**.
- **CloudWatch Logs** (light usage): **under £1/month**.

**Total: about £15/month** for a minimal always-on stack, excluding data transfer and operator time.

## Architecture

```
┌─────────────────────────────────────┐
│ EC2 t4g.small eu-west-1 (Dublin)    │
│                                     │
│  ┌─────────┐  ┌──────────┐          │
│  │ redis   │  │ postgres │          │
│  └────┬────┘  └─────┬────┘          │
│       │             │               │
│  ┌────▼─────────────▼──┐            │
│  │ ingestion           │──── Gamma REST (public)
│  │ strategy_runner     │
│  │ simulator           │
│  │ risk_manager        │
│  └─────────────────────┘            │
└──────────────┬──────────────────────┘
               │
          Elastic IP (stable)
```

## Bootstrap note

`deploy/bootstrap.sh` installs `docker` and `docker-compose-plugin` on Amazon Linux 2023 so `docker compose` matches the unit file in this repo.
