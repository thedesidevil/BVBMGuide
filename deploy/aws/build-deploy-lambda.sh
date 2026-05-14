#!/usr/bin/env bash
# Build a versioned Lambda zip for the Library QC UI.
#
# Usage:
#   ./deploy/aws/build-deploy-lambda.sh
#   ./deploy/aws/build-deploy-lambda.sh --upload
#   ./deploy/aws/build-deploy-lambda.sh --deploy --function-name library-qc
#
# Environment (optional overrides):
#   AWS_PROFILE          default: bvbm
#   AWS_REGION           default: ap-south-1
#   LAMBDA_FUNCTION_NAME  default: empty; required for --deploy unless --function-name is set

set -euo pipefail

export AWS_PROFILE="${AWS_PROFILE:-bvbm}"
export AWS_REGION="${AWS_REGION:-ap-south-1}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

S3_DEPLOY_BUCKET="bvbm-code"
S3_DEPLOY_PREFIX="aig-library-builder"

LAMBDA_FUNCTION_NAME="${LAMBDA_FUNCTION_NAME:-}"

read_package_version() {
  if [[ -f "$REPO_ROOT/VERSION" ]]; then
    head -n1 "$REPO_ROOT/VERSION" | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
  elif v=$(git -C "$REPO_ROOT" describe --tags --always --dirty 2>/dev/null); then
    echo "$v"
  else
    echo "0.0.0"
  fi
}

safe_version_slug() {
  echo "$1" | tr -c 'A-Za-z0-9._-' '-' | sed -e 's/--*/-/g' -e 's/^-//' -e 's/-$//'
}

PACKAGE_VERSION=$(read_package_version)
VERSION_SLUG=$(safe_version_slug "$PACKAGE_VERSION")
[[ -z "$VERSION_SLUG" ]] && VERSION_SLUG="0"
BUILD_ID=$(date -u +%Y%m%dT%H%M%SZ)
ZIP_BASENAME="function-${VERSION_SLUG}-${BUILD_ID}.zip"

UPLOAD_S3=false
DEPLOY_LAMBDA=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --upload) UPLOAD_S3=true ;;
    --deploy)
      DEPLOY_LAMBDA=true
      UPLOAD_S3=true
      ;;
    --function-name)
      [[ $# -ge 2 ]] || { echo "Missing value for --function-name" >&2; exit 1; }
      LAMBDA_FUNCTION_NAME="$2"
      shift 2
      continue
      ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--upload] [--deploy [--function-name NAME]]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

echo "==> Repository root: $REPO_ROOT"
echo "==> AWS_PROFILE=${AWS_PROFILE}  AWS_REGION=${AWS_REGION}"
cd "$REPO_ROOT"
mkdir -p build

echo "==> Package version: $PACKAGE_VERSION  (artifact: $ZIP_BASENAME)"

echo "==> Cleaning build/lambda"
rm -rf build/lambda
mkdir -p build/lambda

echo "==> Installing dependencies (manylinux2014_aarch64, cp314)"
python3 -m pip install \
  -r deploy/aws/lambda-requirements.txt \
  --platform manylinux2014_aarch64 \
  --python-version 314 \
  --implementation cp \
  --only-binary=:all: \
  -t build/lambda/ \
  --quiet

echo "==> Copying application code into build/lambda"
cp -R src build/lambda/

echo "==> Copying frontend build"
if [[ -d "ui-frontend/dist" ]]; then
  mkdir -p build/lambda/ui-frontend
  cp -R ui-frontend/dist build/lambda/ui-frontend/
else
  echo "WARNING: ui-frontend/dist not found — run 'cd ui-frontend && npm run build' first"
fi

echo "==> Removing __pycache__ and .pyc"
find build/lambda -depth -type d -name '__pycache__' -exec rm -rf {} \;
find build/lambda -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

echo "==> Creating build/$ZIP_BASENAME"
(cd build/lambda && zip -qr "../$ZIP_BASENAME" .)

cp -f "$REPO_ROOT/build/$ZIP_BASENAME" "$REPO_ROOT/build/function.zip"
echo "$ZIP_BASENAME" > "$REPO_ROOT/build/.lambda-package-latest.txt"

echo "==> Artifact: build/$ZIP_BASENAME"
ls -lh "$REPO_ROOT/build/$ZIP_BASENAME"

S3_KEY="${S3_DEPLOY_PREFIX}/${ZIP_BASENAME}"

if "$UPLOAD_S3"; then
  S3_URI="s3://${S3_DEPLOY_BUCKET}/${S3_KEY}"
  echo "==> Uploading to ${S3_URI}"
  aws s3 cp "$REPO_ROOT/build/$ZIP_BASENAME" "$S3_URI"
fi

if "$DEPLOY_LAMBDA"; then
  if [[ -z "${LAMBDA_FUNCTION_NAME}" ]]; then
    echo "error: --deploy requires --function-name NAME or env LAMBDA_FUNCTION_NAME" >&2
    exit 1
  fi
  echo "==> Updating Lambda: ${LAMBDA_FUNCTION_NAME}"
  aws lambda update-function-code \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --s3-bucket "$S3_DEPLOY_BUCKET" \
    --s3-key "$S3_KEY" \
    --region "$AWS_REGION"
  echo "==> Done."
fi
