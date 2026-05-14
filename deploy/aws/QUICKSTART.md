# Library QC UI — AWS Deployment

## Prerequisites

- AWS CLI configured with profile `bvbm` (region `ap-south-1`)
- Python 3.14+, Node.js 18+ (for frontend build)
- S3 bucket `bvbm-aig-library` created in `ap-south-1`

## Initial Setup

### 1. Create S3 bucket

```bash
aws s3 mb s3://bvbm-aig-library --region ap-south-1 --profile bvbm
```

### 2. Upload existing library_db

```bash
aws s3 sync library_db/ s3://bvbm-aig-library/library_db/ \
  --exclude "_staging/*" \
  --profile bvbm --region ap-south-1
```

### 3. Build frontend

```bash
cd ui-frontend && npm run build && cd ..
```

### 4. Build deployment zip

```bash
./deploy/aws/build-deploy-lambda.sh
```

### 5. Create Lambda function (first time)

```bash
aws lambda create-function \
  --function-name library-qc \
  --runtime python3.14 \
  --architectures arm64 \
  --handler src.library.ui.lambda_handler.handler \
  --role arn:aws:iam::ACCOUNT_ID:role/lambda-library-qc \
  --zip-file fileb://build/function.zip \
  --timeout 900 \
  --memory-size 1024 \
  --environment "Variables={LIBRARY_S3_BUCKET=bvbm-aig-library,LIBRARY_S3_PREFIX=library_db,AI_API_KEY=...,AI_BASE_URL=...,AI_MODEL=claude-sonnet-4-20250514}" \
  --region ap-south-1 \
  --profile bvbm
```

### 6. Create Function URL

```bash
aws lambda create-function-url-config \
  --function-name library-qc \
  --auth-type NONE \
  --cors "AllowOrigins=*,AllowMethods=*,AllowHeaders=*" \
  --region ap-south-1 \
  --profile bvbm
```

### 7. Add resource policy for public access

```bash
aws lambda add-permission \
  --function-name library-qc \
  --statement-id FunctionURLPublicAccess \
  --action lambda:InvokeFunctionUrl \
  --principal "*" \
  --function-url-auth-type NONE \
  --region ap-south-1 \
  --profile bvbm
```

## Subsequent Deploys

```bash
./deploy/aws/build-deploy-lambda.sh --deploy --function-name library-qc
```

## IAM Role

The Lambda execution role (`lambda-library-qc`) needs:
- `AWSLambdaBasicExecutionRole` (CloudWatch logs)
- S3 access to `bvbm-aig-library` bucket:

```json
{
  "Effect": "Allow",
  "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
  "Resource": [
    "arn:aws:s3:::bvbm-aig-library",
    "arn:aws:s3:::bvbm-aig-library/*"
  ]
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LIBRARY_S3_BUCKET` | Yes | S3 bucket name |
| `LIBRARY_S3_PREFIX` | No | Key prefix (default: `library_db`) |
| `AI_API_KEY` | Yes | For classify/extract AI calls |
| `AI_BASE_URL` | Yes | OpenAI-compatible endpoint |
| `AI_MODEL` | Yes | Model name |
| `GOOGLE_MAPS_API_KEY` | No | For geocoding |
