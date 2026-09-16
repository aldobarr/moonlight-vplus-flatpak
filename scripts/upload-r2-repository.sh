#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 ASSET_DIRECTORY R2_BUCKET_NAME OBJECT_PREFIX WRANGLER" >&2
  exit 2
fi

asset_directory=$1
r2_bucket_name=$2
object_prefix=$3
wrangler=$4

if [[ ! -d "$asset_directory/repo" ]]; then
  echo "Flatpak repository is missing: $asset_directory/repo" >&2
  exit 1
fi
if [[ ! "$r2_bucket_name" =~ ^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$ ]]; then
  echo "Invalid R2 bucket name: $r2_bucket_name" >&2
  exit 1
fi
if [[ ! "$object_prefix" =~ ^releases/[0-9A-Za-z][0-9A-Za-z._+-]*$ ]]; then
  echo "Invalid R2 object prefix: $object_prefix" >&2
  exit 1
fi
if [[ ! -x "$wrangler" ]]; then
  echo "Wrangler is unavailable: $wrangler" >&2
  exit 1
fi

mapfile -d '' repository_files < <(find "$asset_directory/repo" -type f -print0)
if [[ ${#repository_files[@]} -eq 0 ]]; then
  echo "Flatpak repository contains no files." >&2
  exit 1
fi

content_type() {
  case "$1" in
    repo/*.png) printf 'image/png' ;;
    *) printf 'application/octet-stream' ;;
  esac
}

cache_control() {
  case "$1" in
    repo/objects/*) printf 'public, max-age=31536000, immutable' ;;
    *) printf 'no-cache' ;;
  esac
}

uploaded_count=0
for repository_file in "${repository_files[@]}"; do
  relative_path=${repository_file#"$asset_directory"/}
  if [[ ! "$relative_path" =~ ^[0-9A-Za-z._/-]+$ ]]; then
    echo "Unsupported R2 object path: $relative_path" >&2
    exit 1
  fi
  if [[ "$relative_path" == /* || "$relative_path" == *"/../"* || "$relative_path" == ../* ]]; then
    echo "Unsafe R2 object path: $relative_path" >&2
    exit 1
  fi

  "$wrangler" r2 object put \
    "$r2_bucket_name/$object_prefix/$relative_path" \
    --file "$repository_file" \
    --content-type "$(content_type "$relative_path")" \
    --cache-control "$(cache_control "$relative_path")" \
    --force \
    --remote
  uploaded_count=$((uploaded_count + 1))
done

echo "Uploaded $uploaded_count Flatpak repository objects to $r2_bucket_name/$object_prefix."
