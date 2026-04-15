#!/bin/bash
# GEX Alerts — one-shot AWS infrastructure setup.
# Run from the repo root: bash aws/setup.sh
# Requires: AWS CLI v2 configured with sufficient IAM permissions.
set -euo pipefail

REGION="ap-south-1"
APP="gex-alerts"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAMBDA_DIR="$SCRIPT_DIR/lambda"

# ════════════════════════════════════════════════════════════
# 0. Collect configuration
# ════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   GEX Alerts — AWS Infrastructure Setup  ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Verify AWS CLI is configured
aws sts get-caller-identity --region "$REGION" > /dev/null || {
  echo "Error: AWS CLI not configured. Run 'aws configure' first."
  exit 1
}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "Account: $ACCOUNT_ID  |  Region: $REGION"
echo ""

read -rp  "Upstox API Key:              " UPSTOX_API_KEY
read -rsp "Upstox API Secret:           " UPSTOX_API_SECRET;   echo
read -rsp "Upstox Access Token (today): " UPSTOX_ACCESS_TOKEN; echo
read -rsp "Telegram Bot Token:          " TELEGRAM_BOT_TOKEN;  echo
read -rp  "Telegram Chat ID:            " TELEGRAM_CHAT_ID
read -rp  "EC2 Key Pair name (for SSH, blank to skip): " KEY_PAIR_NAME
echo ""

# ════════════════════════════════════════════════════════════
# 1. SSM Parameter Store — store secrets
# ════════════════════════════════════════════════════════════
echo "[1/8] Storing secrets in SSM Parameter Store..."

_ssm_put_secure() {
  aws ssm put-parameter --name "/$APP/$1" --value "$2" \
    --type SecureString --overwrite --region "$REGION" > /dev/null
}
_ssm_put() {
  aws ssm put-parameter --name "/$APP/$1" --value "$2" \
    --type String --overwrite --region "$REGION" > /dev/null
}

_ssm_put_secure UPSTOX_API_KEY      "$UPSTOX_API_KEY"
_ssm_put_secure UPSTOX_API_SECRET   "$UPSTOX_API_SECRET"
_ssm_put_secure UPSTOX_ACCESS_TOKEN "$UPSTOX_ACCESS_TOKEN"
_ssm_put_secure TELEGRAM_BOT_TOKEN  "$TELEGRAM_BOT_TOKEN"
_ssm_put        TELEGRAM_CHAT_ID    "$TELEGRAM_CHAT_ID"
echo "    Done."

# ════════════════════════════════════════════════════════════
# 2. IAM roles
# ════════════════════════════════════════════════════════════
echo "[2/8] Creating IAM roles..."

# ── EC2 role (reads SSM) ──
aws iam create-role \
  --role-name "$APP-ec2-role" \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  --region "$REGION" > /dev/null 2>&1 || true

aws iam put-role-policy \
  --role-name "$APP-ec2-role" \
  --policy-name "ssm-read" \
  --policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[{
      \"Effect\":\"Allow\",
      \"Action\":[\"ssm:GetParameter\",\"ssm:GetParameters\"],
      \"Resource\":\"arn:aws:ssm:$REGION:$ACCOUNT_ID:parameter/$APP/*\"
    }]
  }" > /dev/null

# SSM agent + S3 deploy bucket access (enables SSM Session Manager and codeless deploy)
aws iam attach-role-policy \
  --role-name "$APP-ec2-role" \
  --policy-arn "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore" > /dev/null 2>&1 || true

aws iam put-role-policy \
  --role-name "$APP-ec2-role" \
  --policy-name "s3-deploy-read" \
  --policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[{
      \"Effect\":\"Allow\",
      \"Action\":[\"s3:GetObject\"],
      \"Resource\":\"arn:aws:s3:::$APP-deploy-$ACCOUNT_ID/*\"
    }]
  }" > /dev/null

aws iam create-instance-profile \
  --instance-profile-name "$APP-ec2-profile" > /dev/null 2>&1 || true

aws iam add-role-to-instance-profile \
  --instance-profile-name "$APP-ec2-profile" \
  --role-name "$APP-ec2-role" > /dev/null 2>&1 || true

# ── Lambda role (reads+writes SSM, starts/stops EC2, writes logs) ──
aws iam create-role \
  --role-name "$APP-lambda-role" \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  --region "$REGION" > /dev/null 2>&1 || true

aws iam put-role-policy \
  --role-name "$APP-lambda-role" \
  --policy-name "gex-lambda-policy" \
  --policy-document "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[
      {
        \"Effect\":\"Allow\",
        \"Action\":[\"ssm:GetParameter\",\"ssm:GetParameters\",\"ssm:PutParameter\"],
        \"Resource\":\"arn:aws:ssm:$REGION:$ACCOUNT_ID:parameter/$APP/*\"
      },
      {
        \"Effect\":\"Allow\",
        \"Action\":[\"ec2:StartInstances\",\"ec2:StopInstances\",\"ec2:DescribeInstances\"],
        \"Resource\":\"*\"
      },
      {
        \"Effect\":\"Allow\",
        \"Action\":[\"logs:CreateLogGroup\",\"logs:CreateLogStream\",\"logs:PutLogEvents\"],
        \"Resource\":\"arn:aws:logs:$REGION:$ACCOUNT_ID:*\"
      }
    ]
  }" > /dev/null

LAMBDA_ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/$APP-lambda-role"
echo "    Done. Waiting 15s for IAM propagation..."
sleep 15

# ════════════════════════════════════════════════════════════
# 3. Lambda functions
# ════════════════════════════════════════════════════════════
echo "[3/8] Deploying Lambda functions..."

_deploy_lambda() {
  local name="$1"
  local zip="/tmp/$APP-$name.zip"

  zip -j "$zip" "$LAMBDA_DIR/$name.py" > /dev/null

  if aws lambda get-function --function-name "$APP-$name" \
       --region "$REGION" > /dev/null 2>&1; then
    aws lambda update-function-code \
      --function-name "$APP-$name" \
      --zip-file "fileb://$zip" \
      --region "$REGION" > /dev/null
  else
    aws lambda create-function \
      --function-name "$APP-$name" \
      --runtime python3.11 \
      --role "$LAMBDA_ROLE_ARN" \
      --handler "$name.handler" \
      --zip-file "fileb://$zip" \
      --timeout 30 \
      --environment "Variables={APP_NAME=$APP}" \
      --region "$REGION" > /dev/null
  fi

  rm "$zip"
  echo "    $name deployed."
}

_deploy_lambda oauth_callback
_deploy_lambda token_notifier
_deploy_lambda ec2_scheduler   # INSTANCE_ID added later after EC2 launch

# ════════════════════════════════════════════════════════════
# 4. API Gateway (HTTP API) for OAuth callback
# ════════════════════════════════════════════════════════════
echo "[4/8] Creating API Gateway..."

# Reuse if already exists
EXISTING_API=$(aws apigatewayv2 get-apis --region "$REGION" \
  --query "Items[?Name=='$APP-oauth'].ApiId" --output text)

if [[ -n "$EXISTING_API" && "$EXISTING_API" != "None" ]]; then
  API_ID="$EXISTING_API"
  echo "    Reusing existing API: $API_ID"
else
  API_ID=$(aws apigatewayv2 create-api \
    --name "$APP-oauth" \
    --protocol-type HTTP \
    --query ApiId \
    --output text \
    --region "$REGION")

  OAUTH_ARN=$(aws lambda get-function \
    --function-name "$APP-oauth_callback" \
    --query Configuration.FunctionArn \
    --output text \
    --region "$REGION")

  INTEG_ID=$(aws apigatewayv2 create-integration \
    --api-id "$API_ID" \
    --integration-type AWS_PROXY \
    --integration-uri "arn:aws:apigateway:$REGION:lambda:path/2015-03-31/functions/$OAUTH_ARN/invocations" \
    --payload-format-version "2.0" \
    --query IntegrationId \
    --output text \
    --region "$REGION")

  aws apigatewayv2 create-route \
    --api-id "$API_ID" \
    --route-key "GET /callback" \
    --target "integrations/$INTEG_ID" \
    --region "$REGION" > /dev/null

  aws apigatewayv2 create-stage \
    --api-id "$API_ID" \
    --stage-name prod \
    --auto-deploy \
    --region "$REGION" > /dev/null

  aws lambda add-permission \
    --function-name "$APP-oauth_callback" \
    --statement-id "apigw-invoke" \
    --action "lambda:InvokeFunction" \
    --principal "apigateway.amazonaws.com" \
    --source-arn "arn:aws:execute-api:$REGION:$ACCOUNT_ID:$API_ID/*/GET/callback" \
    --region "$REGION" > /dev/null 2>&1 || true
fi

CALLBACK_URL="https://$API_ID.execute-api.$REGION.amazonaws.com/prod/callback"
_ssm_put UPSTOX_REDIRECT_URI "$CALLBACK_URL"
echo "    Callback URL: $CALLBACK_URL"

# ════════════════════════════════════════════════════════════
# 5. Security group
# ════════════════════════════════════════════════════════════
echo "[5/8] Creating security group..."

VPC_ID=$(aws ec2 describe-vpcs \
  --filters "Name=isDefault,Values=true" \
  --query "Vpcs[0].VpcId" \
  --output text \
  --region "$REGION")

SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=$APP-sg" "Name=vpc-id,Values=$VPC_ID" \
  --query "SecurityGroups[0].GroupId" \
  --output text \
  --region "$REGION" 2>/dev/null || true)

if [[ -z "$SG_ID" || "$SG_ID" == "None" ]]; then
  SG_ID=$(aws ec2 create-security-group \
    --group-name "$APP-sg" \
    --description "GEX Alerts EC2" \
    --vpc-id "$VPC_ID" \
    --query GroupId \
    --output text \
    --region "$REGION")

  # Outbound: HTTPS only (Upstox + Telegram APIs)
  aws ec2 revoke-security-group-egress \
    --group-id "$SG_ID" \
    --ip-permissions '[{"IpProtocol":"-1","IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]' \
    --region "$REGION" > /dev/null 2>&1 || true

  aws ec2 authorize-security-group-egress \
    --group-id "$SG_ID" \
    --protocol tcp --port 443 --cidr 0.0.0.0/0 \
    --region "$REGION" > /dev/null
fi

# EC2 Instance Connect: allow inbound SSH from the service IP range for ap-south-1.
# deploy.sh also opens SSH from the deployer's current IP at deploy time.
aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol tcp --port 22 --cidr 13.126.255.0/29 \
  --region "$REGION" > /dev/null 2>&1 || true

echo "    Security group: $SG_ID"

# ════════════════════════════════════════════════════════════
# 5b. S3 deploy bucket
# ════════════════════════════════════════════════════════════
DEPLOY_BUCKET="$APP-deploy-$ACCOUNT_ID"
aws s3 mb "s3://$DEPLOY_BUCKET" --region "$REGION" > /dev/null 2>&1 || true
aws s3api put-bucket-lifecycle-configuration \
  --bucket "$DEPLOY_BUCKET" \
  --lifecycle-configuration '{"Rules":[{"ID":"expire-artifacts","Status":"Enabled","Expiration":{"Days":7},"Filter":{"Prefix":""}}]}' \
  --region "$REGION" > /dev/null 2>&1 || true
echo "    Deploy bucket: $DEPLOY_BUCKET"

# ════════════════════════════════════════════════════════════
# 6. EC2 instance
# ════════════════════════════════════════════════════════════
echo "[6/8] Launching EC2 instance..."

# Skip if already exists
EXISTING_INSTANCE=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$APP" \
            "Name=instance-state-name,Values=running,stopped,pending" \
  --query "Reservations[0].Instances[0].InstanceId" \
  --output text \
  --region "$REGION" 2>/dev/null || true)

if [[ -n "$EXISTING_INSTANCE" && "$EXISTING_INSTANCE" != "None" ]]; then
  INSTANCE_ID="$EXISTING_INSTANCE"
  echo "    Reusing existing instance: $INSTANCE_ID"
else
  # Latest Amazon Linux 2023 arm64 AMI
  AMI_ID=$(aws ec2 describe-images \
    --owners amazon \
    --filters "Name=name,Values=al2023-ami-*-arm64" \
              "Name=state,Values=available" \
    --query "sort_by(Images, &CreationDate)[-1].ImageId" \
    --output text \
    --region "$REGION")

  LAUNCH_ARGS=(
    --image-id "$AMI_ID"
    --instance-type t4g.nano
    --iam-instance-profile "Name=$APP-ec2-profile"
    --security-group-ids "$SG_ID"
    --user-data "file://$SCRIPT_DIR/ec2_userdata.sh"
    --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":8,"VolumeType":"gp3"}}]'
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$APP}]"
    --region "$REGION"
  )
  [[ -n "$KEY_PAIR_NAME" ]] && LAUNCH_ARGS+=(--key-name "$KEY_PAIR_NAME")

  INSTANCE_ID=$(aws ec2 run-instances "${LAUNCH_ARGS[@]}" \
    --query "Instances[0].InstanceId" --output text)
  echo "    Launched: $INSTANCE_ID (AMI: $AMI_ID)"
fi

# Inject instance ID into ec2_scheduler Lambda
aws lambda update-function-configuration \
  --function-name "$APP-ec2_scheduler" \
  --environment "Variables={APP_NAME=$APP,INSTANCE_ID=$INSTANCE_ID}" \
  --region "$REGION" > /dev/null

# ════════════════════════════════════════════════════════════
# 7. EventBridge rules (all times UTC; IST = UTC+5:30)
# ════════════════════════════════════════════════════════════
echo "[7/8] Creating EventBridge rules..."

SCHEDULER_ARN=$(aws lambda get-function \
  --function-name "$APP-ec2_scheduler" \
  --query Configuration.FunctionArn --output text --region "$REGION")

NOTIFIER_ARN=$(aws lambda get-function \
  --function-name "$APP-token_notifier" \
  --query Configuration.FunctionArn --output text --region "$REGION")

_create_rule() {
  local rule_name="$1"
  local schedule="$2"    # UTC cron
  local target_arn="$3"
  local input="${4:-}"   # optional JSON payload for the Lambda event

  aws events put-rule \
    --name "$rule_name" \
    --schedule-expression "cron($schedule)" \
    --state ENABLED \
    --region "$REGION" > /dev/null

  # --targets requires Input to be a JSON-encoded *string*, not a raw object.
  # The shorthand parser misinterprets bare {} / {"k":"v"} as dicts, so we
  # build a proper JSON array and pass it directly.
  local target_json
  if [[ -n "$input" ]]; then
    local escaped
    escaped=$(printf '%s' "$input" | sed 's/\\/\\\\/g; s/"/\\"/g')
    target_json="[{\"Id\":\"1\",\"Arn\":\"$target_arn\",\"Input\":\"$escaped\"}]"
  else
    target_json="[{\"Id\":\"1\",\"Arn\":\"$target_arn\"}]"
  fi

  aws events put-targets \
    --rule "$rule_name" \
    --targets "$target_json" \
    --region "$REGION" > /dev/null

  aws lambda add-permission \
    --function-name "$target_arn" \
    --statement-id "eb-$rule_name" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "arn:aws:events:$REGION:$ACCOUNT_ID:rule/$rule_name" \
    --region "$REGION" > /dev/null 2>&1 || true
}

# 8:50 AM IST  = 3:20 AM UTC  → send Telegram auth link (no payload needed)
_create_rule "$APP-token-notify" "20 3 ? * MON-FRI *" "$NOTIFIER_ARN"
# 9:05 AM IST  = 3:35 AM UTC  → start EC2
_create_rule "$APP-ec2-start"    "35 3 ? * MON-FRI *" "$SCHEDULER_ARN" '{"action":"start"}'
# 3:40 PM IST  = 10:10 AM UTC → stop EC2
_create_rule "$APP-ec2-stop"     "10 10 ? * MON-FRI *" "$SCHEDULER_ARN" '{"action":"stop"}'

echo "    Done."

# ════════════════════════════════════════════════════════════
# 8. Deploy code (waits for instance to pass status checks)
# ════════════════════════════════════════════════════════════
echo "[8/8] Waiting for EC2 to pass status checks (up to 3 min)..."
aws ec2 wait instance-status-ok \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION"

if [[ -n "$KEY_PAIR_NAME" ]]; then
  KEY_FILE="$HOME/.ssh/$KEY_PAIR_NAME.pem"
  if [[ -f "$KEY_FILE" ]]; then
    echo "    Deploying code..."
    bash "$SCRIPT_DIR/deploy.sh" "$INSTANCE_ID" "$KEY_FILE"
  else
    echo "    Key file $KEY_FILE not found."
    echo "    Run manually: bash aws/deploy.sh $INSTANCE_ID <path-to-key.pem>"
  fi
else
  echo "    No key pair — skipping code deploy."
  echo "    Run manually: bash aws/deploy.sh $INSTANCE_ID <path-to-key.pem>"
fi

# ════════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════════
EC2_IP=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --query "Reservations[0].Instances[0].PublicIpAddress" \
  --output text --region "$REGION" 2>/dev/null || echo "N/A")

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║           Setup complete!                        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "  Instance:     $INSTANCE_ID  ($EC2_IP)"
echo "  Callback URL: $CALLBACK_URL"
echo "  Est. cost:    ~\$1.30/month"
echo ""
echo "  ⚠️  ACTION REQUIRED:"
echo "  Update your Upstox Developer Console:"
echo "    Redirect URI → $CALLBACK_URL"
echo ""
echo "  Daily schedule (IST):"
echo "    8:50 AM  Telegram sends auth link"
echo "    9:05 AM  EC2 starts, reads fresh token from SSM"
echo "    3:40 PM  EC2 stops"
echo ""
echo "  To deploy code changes:"
echo "    bash aws/deploy.sh $INSTANCE_ID"
echo ""
echo "  To update a secret manually:"
echo "    aws ssm put-parameter --name /$APP/UPSTOX_ACCESS_TOKEN \\"
echo "      --value <token> --type SecureString --overwrite --region $REGION"
echo ""
