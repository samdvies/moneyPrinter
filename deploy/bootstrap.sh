#!/bin/bash
set -euo pipefail
# Runs as EC2 user-data on first boot, Amazon Linux 2023 arm64.

dnf update -y
dnf install -y git docker docker-compose-plugin
systemctl enable --now docker
usermod -aG docker ec2-user

mkdir -p /opt
cd /opt
git clone https://github.com/samdvies/moneyPrinter.git algo-betting
cd algo-betting

cat >/etc/systemd/system/algo-betting.service <<'EOF'
[Unit]
Description=algo-betting docker compose stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/algo-betting
EnvironmentFile=/opt/algo-betting/deploy/.env.prod
ExecStart=/usr/bin/docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod up -d --build
ExecStop=/usr/bin/docker compose -f deploy/docker-compose.prod.yml down

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable algo-betting.service
# Don't start yet — operator must provision .env.prod first.
