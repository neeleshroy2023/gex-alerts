#!/bin/bash
# Deploy local code to EC2 via SSH.
# Uses ~/.ssh/gex-alerts-deploy key (injected into the instance via cloud-boothook user data).
# Opens SSH from your current IP, deploys, then revokes the rule.
# Usage: ./aws/deploy.sh <instance-id>
set -euo pipefail

INSTANCE_ID="${1:?Usage: $0 <instance-id>}"
REGION="ap-south-1"
APP="gex-alerts"
KEY="$HOME/.ssh/gex-alerts-deploy"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ZIPFILE="/tmp/gex-app-$$.zip"

[[ -f "$KEY" ]] || { echo "Error: SSH key not found at $KEY. Run: ssh-keygen -t ed25519 -f $KEY -N ''"; exit 1; }

# ---- Ensure instance is running ----
STATE=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --query "Reservations[0].Instances[0].State.Name" \
  --output text --region "$REGION")

if [[ "$STATE" == "stopped" ]]; then
  echo "Instance stopped — starting..."
  aws ec2 start-instances --instance-ids "$INSTANCE_ID" --region "$REGION" > /dev/null
  aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"
  echo "Instance running. Waiting 20s for SSH..."
  sleep 20
elif [[ "$STATE" != "running" ]]; then
  echo "Error: instance is in state '$STATE'."
  exit 1
fi

# ---- Instance metadata ----
read -r EC2_IP SG_ID < <(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --query "Reservations[0].Instances[0].[PublicIpAddress,SecurityGroups[0].GroupId]" \
  --output text --region "$REGION")

MY_IP=$(curl -sf https://checkip.amazonaws.com)/32
echo "Target: ec2-user@$EC2_IP"

# ---- Package app ----
echo "Packaging..."
(cd "$REPO_ROOT" && zip -qr "$ZIPFILE" . \
  --exclude "*.git/*" \
  --exclude "tests/*" \
  --exclude "__pycache__/*" \
  --exclude "*.pyc" \
  --exclude "*.db" \
  --exclude "logs/*" \
  --exclude ".env" \
  --exclude "aws/*")

# ---- Open SSH from current IP ----
echo "Opening SSH from $MY_IP..."
aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" --protocol tcp --port 22 --cidr "$MY_IP" \
  --region "$REGION" > /dev/null 2>&1 || true

cleanup() {
  echo "Revoking SSH rule..."
  aws ec2 revoke-security-group-ingress \
    --group-id "$SG_ID" --protocol tcp --port 22 --cidr "$MY_IP" \
    --region "$REGION" > /dev/null 2>&1 || true
  rm -f "$ZIPFILE"
}
trap cleanup EXIT

SSH_OPTS="-i $KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"

# ---- Upload zip ----
echo "Uploading..."
scp $SSH_OPTS "$ZIPFILE" "ec2-user@$EC2_IP:/tmp/gex-app.zip"

# ---- Install and restart ----
echo "Installing..."
# shellcheck disable=SC2029
ssh $SSH_OPTS "ec2-user@$EC2_IP" << 'REMOTE'
set -euo pipefail
sudo unzip -qo /tmp/gex-app.zip -d /app/gex-alerts/
sudo /app/venv/bin/pip install -q -r /app/gex-alerts/requirements.txt
sudo chown -R gex:gex /app/gex-alerts /app/venv
sudo systemctl restart gex-alerts
sleep 3
sudo systemctl status gex-alerts --no-pager -l
rm /tmp/gex-app.zip
REMOTE

echo "Deploy complete."
