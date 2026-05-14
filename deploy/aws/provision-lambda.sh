#!/usr/bin/env bash
# Provision the IAM role and Lambda function for Library QC UI.
#
# Usage:
#   ./deploy/aws/provision-lambda.sh
#   ./deploy/aws/provision-lambda.sh --s3-key aig-library-builder/function-4695d6f-20260514T115802Z.zip
#
# This script is idempotent — safe to re-run. It will skip resources that
# already exist and update the function code if the Lambda already exists.
#
# Environment (optional overrides):
#   AWS_PROFILE              default: bvbm
#   AWS_REGION               default: ap-south-1
#   LAMBDA_FUNCTION_NAME     default: library-builder
#   LAMBDA_ROLE_NAME         default: lambda-library-builder
#   CODE_S3_BUCKET           default: bvbm-code (bucket containing the zip)
#   CODE_S3_KEY              default: latest from build/.lambda-package-latest.txt
#   DATA_S3_BUCKET           default: bvbm-aig-library (bucket the Lambda reads/writes)

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bvbm}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

LAMBDA_FUNCTION_NAME="${LAMBDA_FUNCTION_NAME:-library-builder}"
LAMBDA_ROLE_NAME="${LAMBDA_ROLE_NAME:-lambda-library-builder}"
CODE_S3_BUCKET="${CODE_S3_BUCKET:-bvbm-code}"
CODE_S3_KEY="${CODE_S3_KEY:-}"
DATA_S3_BUCKET="${DATA_S3_BUCKET:-bvbm-aig-library}"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --s3-key)
      [[ $# -ge 2 ]] || { echo "Missing value for --s3-key" >&2; exit 1; }
      CODE_S3_KEY="$2"
      shift 2
      continue
      ;;
    --function-name)
      [[ $# -ge 2 ]] || { echo "Missing value for --function-name" >&2; exit 1; }
      LAMBDA_FUNCTION_NAME="$2"
      shift 2
      continue
      ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--s3-key S3_KEY] [--function-name NAME]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

# Resolve S3 key from build output if not specified
if [[ -z "$CODE_S3_KEY" ]]; then
  LATEST_FILE="$REPO_ROOT/build/.lambda-package-latest.txt"
  if [[ -f "$LATEST_FILE" ]]; then
    ZIP_NAME=$(cat "$LATEST_FILE" | tr -d '\r\n')
    CODE_S3_KEY="aig-library-builder/${ZIP_NAME}"
  else
    echo "error: No --s3-key specified and build/.lambda-package-latest.txt not found." >&2
    echo "       Run build-deploy-lambda.sh first, or pass --s3-key explicitly." >&2
    exit 1
  fi
fi

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${LAMBDA_ROLE_NAME}"

echo "==> Configuration:"
echo "    Function:    ${LAMBDA_FUNCTION_NAME}"
echo "    Role:        ${LAMBDA_ROLE_NAME}"
echo "    Code:        s3://${CODE_S3_BUCKET}/${CODE_S3_KEY}"
echo "    Data bucket: ${DATA_S3_BUCKET}"
echo "    Region:      ${AWS_REGION}"
echo "    Account:     ${AWS_ACCOUNT_ID}"
echo ""

# --- Step 1: Create IAM Role ---
echo "==> Step 1: IAM Role"

TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}'

if aws iam get-role --role-name "$LAMBDA_ROLE_NAME" &>/dev/null; then
  echo "    Role '${LAMBDA_ROLE_NAME}' already exists — skipping creation."
else
  echo "    Creating role '${LAMBDA_ROLE_NAME}'..."
  aws iam create-role \
    --role-name "$LAMBDA_ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "Execution role for ${LAMBDA_FUNCTION_NAME} Lambda" \
    --output text --query 'Role.Arn'
fi

# --- Step 2: Attach managed policy ---
echo "==> Step 2: Attach AWSLambdaBasicExecutionRole"
aws iam attach-role-policy \
  --role-name "$LAMBDA_ROLE_NAME" \
  --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null || true
echo "    Done."

# --- Step 3: Inline S3 policy (data bucket read/write + code bucket read) ---
echo "==> Step 3: S3 access policy"

S3_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DataBucketAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::${DATA_S3_BUCKET}",
        "arn:aws:s3:::${DATA_S3_BUCKET}/*"
      ]
    },
    {
      "Sid": "CodeBucketRead",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": [
        "arn:aws:s3:::${CODE_S3_BUCKET}",
        "arn:aws:s3:::${CODE_S3_BUCKET}/*"
      ]
    }
  ]
}
EOF
)

aws iam put-role-policy \
  --role-name "$LAMBDA_ROLE_NAME" \
  --policy-name "S3Access" \
  --policy-document "$S3_POLICY"
echo "    Inline policy 'S3Access' applied."

# --- Step 4: Wait for IAM propagation ---
echo "==> Step 4: Waiting 10s for IAM propagation..."
sleep 10

# --- Step 5: Create or update Lambda function ---
echo "==> Step 5: Lambda function"

ENV_VARS="Variables={LIBRARY_S3_BUCKET=${DATA_S3_BUCKET},LIBRARY_S3_PREFIX=library_db}"

if aws lambda get-function --function-name "$LAMBDA_FUNCTION_NAME" &>/dev/null; then
  echo "    Function '${LAMBDA_FUNCTION_NAME}' exists — updating code..."
  aws lambda update-function-code \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --s3-bucket "$CODE_S3_BUCKET" \
    --s3-key "$CODE_S3_KEY" \
    --region "$AWS_REGION" \
    --output text --query 'FunctionArn'
else
  echo "    Creating function '${LAMBDA_FUNCTION_NAME}'..."
  aws lambda create-function \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --runtime python3.14 \
    --architectures arm64 \
    --handler src.library.ui.lambda_handler.handler \
    --role "$ROLE_ARN" \
    --code "S3Bucket=${CODE_S3_BUCKET},S3Key=${CODE_S3_KEY}" \
    --timeout 900 \
    --memory-size 512 \
    --environment "$ENV_VARS" \
    --region "$AWS_REGION" \
    --output text --query 'FunctionArn'
fi

# Wait for function to be Active
echo "    Waiting for function to become Active..."
aws lambda wait function-active-v2 --function-name "$LAMBDA_FUNCTION_NAME" 2>/dev/null \
  || aws lambda wait function-active --function-name "$LAMBDA_FUNCTION_NAME" 2>/dev/null \
  || sleep 5
echo "    Function is Active."

# --- Step 6: Function URL ---
echo "==> Step 6: Function URL"

EXISTING_URL=$(aws lambda get-function-url-config --function-name "$LAMBDA_FUNCTION_NAME" 2>/dev/null \
  | grep -o '"FunctionUrl": "[^"]*"' | cut -d'"' -f4 || true)

if [[ -n "$EXISTING_URL" ]]; then
  echo "    Function URL already configured: ${EXISTING_URL}"
else
  FUNCTION_URL=$(aws lambda create-function-url-config \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --auth-type NONE \
    --cors "AllowOrigins=*,AllowMethods=*,AllowHeaders=*" \
    --region "$AWS_REGION" \
    --output text --query 'FunctionUrl')
  echo "    Created Function URL: ${FUNCTION_URL}"
fi

# --- Step 7: Public access permission ---
echo "==> Step 7: Public access permission"

aws lambda add-permission \
  --function-name "$LAMBDA_FUNCTION_NAME" \
  --statement-id FunctionURLPublicAccess \
  --action lambda:InvokeFunctionUrl \
  --principal "*" \
  --function-url-auth-type NONE \
  --region "$AWS_REGION" 2>/dev/null \
  && echo "    Permission added." \
  || echo "    Permission already exists — skipping."

# --- Done ---
echo ""
echo "==> Provisioning complete!"
FINAL_URL=$(aws lambda get-function-url-config --function-name "$LAMBDA_FUNCTION_NAME" \
  --output text --query 'FunctionUrl' 2>/dev/null || echo "(url pending)")
echo "    Function URL: ${FINAL_URL}"
echo ""
echo "    To set AI keys (required for classify/extract):"
echo "    aws lambda update-function-configuration \\"
echo "      --function-name ${LAMBDA_FUNCTION_NAME} \\"
echo "      --environment \"Variables={LIBRARY_S3_BUCKET=${DATA_S3_BUCKET},LIBRARY_S3_PREFIX=library_db,AI_API_KEY=<key>,AI_BASE_URL=<url>,AI_MODEL=<model>}\" \\"
echo "      --profile ${AWS_PROFILE} --region ${AWS_REGION}"
