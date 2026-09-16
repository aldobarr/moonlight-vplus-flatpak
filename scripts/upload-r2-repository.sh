#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 ASSET_DIRECTORY R2_BUCKET_NAME RCLONE" >&2
  exit 2
fi

asset_directory=$1
r2_bucket_name=$2
rclone=$3
: "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID is required}"
: "${CLOUDFLARE_R2_ACCESS_KEY_ID:?CLOUDFLARE_R2_ACCESS_KEY_ID is required}"
: "${CLOUDFLARE_R2_SECRET_ACCESS_KEY:?CLOUDFLARE_R2_SECRET_ACCESS_KEY is required}"

if [[ ! -d "$asset_directory/repo" ]]; then
  echo "Flatpak repository is missing: $asset_directory/repo" >&2
  exit 1
fi
if [[ ! "$r2_bucket_name" =~ ^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$ ]]; then
  echo "Invalid R2 bucket name: $r2_bucket_name" >&2
  exit 1
fi
if ! command -v "$rclone" >/dev/null; then
  echo "rclone is unavailable: $rclone" >&2
  exit 1
fi

mapfile -d '' repository_files < <(find "$asset_directory/repo" -type f -print0)
if [[ ${#repository_files[@]} -eq 0 ]]; then
  echo "Flatpak repository contains no files." >&2
  exit 1
fi

export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$CLOUDFLARE_R2_ACCESS_KEY_ID"
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$CLOUDFLARE_R2_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_R2_ENDPOINT="https://${CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"
export RCLONE_CONFIG_R2_REGION=auto
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true

rclone_arguments=(
  --checkers 32
  --transfers 16
  --fast-list
  --retries 5
  --low-level-retries 20
  --stats 30s
  --stats-one-line
)
repository_directory="$asset_directory/repo"

echo "Uploading ${#repository_files[@]} Flatpak repository files to $r2_bucket_name with parallel R2 transfers."
"$rclone" copy \
  "$repository_directory/objects" \
  "r2:$r2_bucket_name/repo/objects" \
  "${rclone_arguments[@]}" \
  --header-upload 'Cache-Control: public, max-age=31536000, immutable'
"$rclone" copy \
  "$repository_directory" \
  "r2:$r2_bucket_name/repo" \
  --exclude 'objects/**' \
  "${rclone_arguments[@]}" \
  --header-upload 'Cache-Control: no-cache'

echo "Uploaded Flatpak repository files to $r2_bucket_name/repo."
