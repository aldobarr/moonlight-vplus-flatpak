#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 REQUIRED_RELEASE_TAG VERIFICATION_ASSET_NAME" >&2
  exit 2
fi
: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

required_release_tag=$1
verification_asset_name=$2
temporary_directory=$(mktemp -d "${RUNNER_TEMP:-/tmp}/moonlight-retention.XXXXXX")

cleanup() {
  rm -rf -- "$temporary_directory"
}
trap cleanup EXIT

for command in gh python3; do
  if ! command -v "$command" >/dev/null; then
    echo "Required command is unavailable: $command" >&2
    exit 1
  fi
done
if [[ -z "$required_release_tag" || -z "$verification_asset_name" ]]; then
  echo "Release tag and verification asset name must not be empty." >&2
  exit 1
fi

release_inventory="$temporary_directory/published-releases.json"
expired_release_tags="$temporary_directory/expired-release-tags.txt"
gh api --paginate --slurp \
  "repos/$GITHUB_REPOSITORY/releases?per_page=100" \
  >"$release_inventory"
python3 scripts/select-expired-releases.py \
  "$release_inventory" \
  --retain 2 \
  --required-tag "$required_release_tag" \
  --verification-asset-name "$verification_asset_name" \
  >"$expired_release_tags"

mapfile -t expired_releases <"$expired_release_tags"
for expired_release in "${expired_releases[@]}"; do
  [[ -n "$expired_release" ]] || continue
  gh release delete "$expired_release" \
    --repo "$GITHUB_REPOSITORY" \
    --cleanup-tag \
    --yes
done

echo "Reconciled verified release retention around $required_release_tag"
