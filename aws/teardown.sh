#!/bin/bash
# AWS teardown script for gex-alerts
# Run with valid AWS credentials in region ap-south-1
# Order: EventBridge -> Lambda -> API GW -> EC2 -> SSM -> S3 -> IAM -> SG -> CloudWatch

set -e

REGION=ap-south-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

echo "Tearing down gex-alerts in $REGION (account: $ACCOUNT)..."

# 1. EventBridge rules
echo "Deleting EventBridge rules..."
for rule in gex-alerts-token-notify gex-alerts-ec2-start gex-alerts-ec2-stop; do
  targets=$(aws events list-targets-by-rule --rule $rule --region $REGION --query 'Targets[].Id' --output text 2>/dev/null || echo "")
  if [ -n "$targets" ]; then
    aws events remove-targets --rule $rule --ids $targets --region $REGION
  fi
  aws events delete-rule --name $rule --region $REGION 2>/dev/null || echo "Rule $rule not found, skipping"
done

# 2. Lambda functions
echo "Deleting Lambda functions..."
for fn in gex-alerts-oauth_callback gex-alerts-token_notifier gex-alerts-ec2_scheduler; do
  aws lambda delete-function --function-name $fn --region $REGION 2>/dev/null || echo "Function $fn not found, skipping"
done

# 3. API Gateway
echo "Deleting API Gateway..."
API_ID=$(aws apigatewayv2 get-apis --region $REGION --query "Items[?Name=='gex-alerts'].ApiId" --output text)
if [ -n "$API_ID" ]; then
  aws apigatewayv2 delete-api --api-id $API_ID --region $REGION
else
  echo "API Gateway not found, skipping"
fi

# 4. EC2 terminate
echo "Terminating EC2 instance..."
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=gex-alerts" "Name=instance-state-name,Values=running,stopped" \
  --region $REGION \
  --query 'Reservations[].Instances[].InstanceId' \
  --output text)
if [ -n "$INSTANCE_ID" ]; then
  aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region $REGION
  echo "Waiting for EC2 termination (needed before SG delete)..."
  aws ec2 wait instance-terminated --instance-ids $INSTANCE_ID --region $REGION
else
  echo "EC2 instance not found, skipping"
fi

# 5. SSM parameters
echo "Deleting SSM parameters..."
for param in UPSTOX_API_KEY UPSTOX_API_SECRET UPSTOX_ACCESS_TOKEN TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID UPSTOX_REDIRECT_URI; do
  aws ssm delete-parameter --name "/gex-alerts/$param" --region $REGION 2>/dev/null || echo "Param $param not found, skipping"
done

# 6. S3 bucket (empty then delete)
echo "Deleting S3 bucket..."
BUCKET="gex-alerts-deploy-$ACCOUNT"
if aws s3 ls "s3://$BUCKET" --region $REGION 2>/dev/null; then
  aws s3 rb s3://$BUCKET --force --region $REGION
else
  echo "Bucket $BUCKET not found, skipping"
fi

# 7. IAM roles and instance profile
echo "Deleting IAM roles..."
aws iam remove-role-from-instance-profile \
  --instance-profile-name gex-alerts-ec2-profile \
  --role-name gex-alerts-ec2-role 2>/dev/null || true
aws iam delete-instance-profile \
  --instance-profile-name gex-alerts-ec2-profile 2>/dev/null || echo "Instance profile not found, skipping"

for role in gex-alerts-ec2-role gex-alerts-lambda-role; do
  # Detach managed policies
  aws iam list-attached-role-policies --role-name $role \
    --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null | \
    tr '\t' '\n' | while read arn; do
      [ -n "$arn" ] && aws iam detach-role-policy --role-name $role --policy-arn $arn
    done
  # Delete inline policies
  aws iam list-role-policies --role-name $role \
    --query 'PolicyNames[]' --output text 2>/dev/null | \
    tr '\t' '\n' | while read pname; do
      [ -n "$pname" ] && aws iam delete-role-policy --role-name $role --policy-name $pname
    done
  aws iam delete-role --role-name $role 2>/dev/null || echo "Role $role not found, skipping"
done

# 8. Security group
echo "Deleting security group..."
SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=gex-alerts-sg" \
  --region $REGION \
  --query 'SecurityGroups[].GroupId' \
  --output text 2>/dev/null)
if [ -n "$SG_ID" ]; then
  aws ec2 delete-security-group --group-id $SG_ID --region $REGION
else
  echo "Security group not found, skipping"
fi

# 9. CloudWatch log groups
echo "Deleting CloudWatch log groups..."
for fn in oauth_callback token_notifier ec2_scheduler; do
  aws logs delete-log-group \
    --log-group-name "/aws/lambda/gex-alerts-$fn" \
    --region $REGION 2>/dev/null || echo "Log group $fn not found, skipping"
done

echo "Teardown complete."
