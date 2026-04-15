#!/bin/bash
# EC2 user data — runs once on first boot (Amazon Linux 2023, arm64)
set -euo pipefail

# ---- System setup ----
dnf update -y
dnf install -y python3.11 python3.11-pip git unzip

# ---- App user and directories ----
useradd -m -s /bin/bash gex 2>/dev/null || true
mkdir -p /app/gex-alerts
python3.11 -m venv /app/venv
chown -R gex:gex /app

# ---- Startup script (reads SSM → runs app) ----
cat > /app/run.sh << 'RUNSCRIPT'
#!/bin/bash
set -euo pipefail
REGION="ap-south-1"
APP="gex-alerts"

echo "[gex] Reading secrets from SSM Parameter Store..."
_ssm() {
  aws ssm get-parameter --name "/$APP/$1" --with-decryption \
    --query Parameter.Value --output text --region "$REGION"
}
_ssm_plain() {
  aws ssm get-parameter --name "/$APP/$1" \
    --query Parameter.Value --output text --region "$REGION"
}

export UPSTOX_API_KEY=$(_ssm UPSTOX_API_KEY)
export UPSTOX_API_SECRET=$(_ssm UPSTOX_API_SECRET)
export UPSTOX_ACCESS_TOKEN=$(_ssm UPSTOX_ACCESS_TOKEN)
export TELEGRAM_BOT_TOKEN=$(_ssm TELEGRAM_BOT_TOKEN)
export TELEGRAM_CHAT_ID=$(_ssm_plain TELEGRAM_CHAT_ID)
export UPSTOX_REDIRECT_URI=$(_ssm_plain UPSTOX_REDIRECT_URI)

echo "[gex] Starting GEX Alert Engine..."
cd /app/gex-alerts
exec /app/venv/bin/python main.py
RUNSCRIPT

chmod +x /app/run.sh
chown gex:gex /app/run.sh

# ---- systemd service ----
cat > /etc/systemd/system/gex-alerts.service << 'SERVICE'
[Unit]
Description=GEX Alert Engine
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=gex
ExecStart=/app/run.sh
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=gex-alerts

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable gex-alerts
echo "[gex] Bootstrap complete. Deploy code with aws/deploy.sh then start: systemctl start gex-alerts"
