#!/bin/bash
set -euo pipefail
# Operator-run: creates a t4g.small in eu-west-1 with Elastic IP (requires AWS CLI).

REGION="${REGION:-eu-west-1}"
KEY_NAME="${KEY_NAME:-algo-betting}"
SG_NAME="${SG_NAME:-algo-betting-sg}"
INSTANCE_TAG="${INSTANCE_TAG:-algo-betting-primary}"
HOME_CIDR="${HOME_CIDR:?set to your home IP in CIDR form, e.g. 203.0.113.10/32}"

VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
if [[ "$VPC_ID" == "None" || -z "$VPC_ID" ]]; then
  echo "error: no default VPC in $REGION" >&2
  exit 1
fi

SG_ID=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)
if [[ "$SG_ID" == "None" || -z "$SG_ID" ]]; then
  SG_ID=$(aws ec2 create-security-group --region "$REGION" --group-name "$SG_NAME" \
    --description "algo-betting SSH" --vpc-id "$VPC_ID" --query 'GroupId' --output text)
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --protocol tcp --port 22 --cidr "$HOME_CIDR" >/dev/null
  echo "created security group $SG_ID"
else
  echo "reusing security group $SG_ID"
fi

if ! aws ec2 describe-key-pairs --region "$REGION" --key-names "$KEY_NAME" &>/dev/null; then
  echo "create an SSH key pair named $KEY_NAME in the console or import one; key not found" >&2
  exit 1
fi

EXISTING=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:Name,Values=$INSTANCE_TAG" "Name=instance-state-name,Values=running,pending,stopping,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)
if [[ -n "$EXISTING" && "$EXISTING" != "None" ]]; then
  PUB=$(aws ec2 describe-addresses --region "$REGION" \
    --filters "Name=instance-id,Values=$EXISTING" --query 'Addresses[0].PublicIp' --output text)
  echo "instance already exists: $EXISTING public_ip=${PUB:-pending}"
  exit 0
fi

AMI_ID=$(aws ec2 describe-images --region "$REGION" --owners amazon \
  --filters 'Name=name,Values=al2023-ami-2023.*-arm64' 'Name=state,Values=available' \
  --query 'sort_by(Images, &CreationDate) | [-1].ImageId' --output text)

IID=$(aws ec2 run-instances --region "$REGION" --image-id "$AMI_ID" --instance-type t4g.small \
  --security-group-ids "$SG_ID" --key-name "$KEY_NAME" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_TAG}]" \
  --user-data file://deploy/bootstrap.sh \
  --query 'Instances[0].InstanceId' --output text)
echo "launched $IID"

aws ec2 wait instance-running --region "$REGION" --instance-ids "$IID"

AID=$(aws ec2 allocate-address --region "$REGION" --domain vpc --query 'AllocationId' --output text)
aws ec2 associate-address --region "$REGION" --allocation-id "$AID" --instance-id "$IID" >/dev/null
EIP=$(aws ec2 describe-addresses --region "$REGION" --allocation-ids "$AID" --query 'Addresses[0].PublicIp' --output text)
echo "Elastic IP: $EIP  (ssh -i ~/.ssh/${KEY_NAME}.pem ec2-user@$EIP)"
