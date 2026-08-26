#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 RELEASE_ASSET_DIRECTORY UPSTREAM_METADATA" >&2
  exit 2
fi
: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GATEWAY_HEALTH_URL:?GATEWAY_HEALTH_URL is required}"
: "${PRODUCTION_VERIFICATION_ASSET:?PRODUCTION_VERIFICATION_ASSET is required}"
: "${REPOSITORY_URL:?REPOSITORY_URL is required}"

asset_directory=$1
upstream_metadata=$2
upstream_tag=$(jq -er '.tag' "$upstream_metadata")
upstream_version=$(jq -er '.version' "$upstream_metadata")
upstream_url=$(jq -er '.html_url' "$upstream_metadata")
upstream_prerelease=$(jq -er '.prerelease' "$upstream_metadata")
build_metadata="$asset_directory/build-metadata.json"
temporary_directory=$(mktemp -d "${RUNNER_TEMP:-/tmp}/moonlight-release.XXXXXX")
release_created=0
production_verified=0

cleanup() {
  status=$?
  if [[ $status -ne 0 && $release_created -eq 1 && $production_verified -eq 0 ]]; then
    echo "Removing incomplete packaging release $release_tag" >&2
    gh release delete "$release_tag" --repo "$GITHUB_REPOSITORY" --cleanup-tag --yes || true
  fi
  rm -rf -- "$temporary_directory"
  exit "$status"
}
trap cleanup EXIT

for command in curl gh jq python3 sha256sum stat; do
  if ! command -v "$command" >/dev/null; then
    echo "Required command is unavailable: $command" >&2
    exit 1
  fi
done
if [[ ! -d "$asset_directory" || ! -f "$upstream_metadata" ]]; then
  echo "Release assets or upstream metadata are missing." >&2
  exit 1
fi
for required_asset in repository-assets.json build-metadata.json "moonlight-qt-${upstream_tag}-x86_64.flatpak"; do
  if [[ ! -f "$asset_directory/$required_asset" ]]; then
    echo "Required release asset is missing: $required_asset" >&2
    exit 1
  fi
done
metadata_upstream_tag=$(jq -er '.upstream.tag' "$build_metadata")
metadata_repository_url=$(jq -er '.repository_url' "$build_metadata")
packaging_commit=$(jq -er '.packaging.commit' "$build_metadata")
release_tag=$(jq -er '.packaging.release_tag' "$build_metadata")
run_id=$(jq -er '.packaging.run_id' "$build_metadata")
run_number=$(jq -er '.packaging.run_number' "$build_metadata")
run_attempt=$(jq -er '.packaging.run_attempt' "$build_metadata")
if [[ "$metadata_upstream_tag" != "$upstream_tag" ]]; then
  echo "Build metadata identifies upstream $metadata_upstream_tag instead of $upstream_tag." >&2
  exit 1
fi
if [[ "$metadata_repository_url" != "$REPOSITORY_URL" ]]; then
  echo "Build metadata uses $metadata_repository_url instead of $REPOSITORY_URL." >&2
  exit 1
fi

mapfile -d '' assets < <(find "$asset_directory" -mindepth 1 -maxdepth 1 -type f -print0 | sort -z)
entry_count=$(find "$asset_directory" -mindepth 1 -maxdepth 1 -printf '.' | wc -c)
if [[ ${#assets[@]} -ne $entry_count ]]; then
  echo "Release asset directory may contain only regular files." >&2
  exit 1
fi
if [[ ${#assets[@]} -ge 1000 ]]; then
  echo "Release has ${#assets[@]} staged assets and no room for its verification record." >&2
  exit 1
fi
for asset in "${assets[@]}"; do
  if [[ $(stat --format=%s "$asset") -ge 2147483648 ]]; then
    echo "Release asset exceeds GitHub's 2 GiB per-file limit: $asset" >&2
    exit 1
  fi
done

curl --fail --silent --show-error --location --max-time 30 "$GATEWAY_HEALTH_URL" >/dev/null

notes_file="$temporary_directory/release-notes.md"
{
  printf 'Automated Flatpak packaging release for upstream Moonlight V+ %s.\n\n' "$upstream_tag"
  printf -- '- Upstream release: %s\n' "$upstream_url"
  printf -- '- Upstream prerelease: %s\n' "$upstream_prerelease"
  printf -- '- Update origin: %s\n' "$REPOSITORY_URL"
  printf -- '- Packaging commit: %s\n' "$packaging_commit"
} >"$notes_file"

gh release create "$release_tag" \
  --repo "$GITHUB_REPOSITORY" \
  --target "$packaging_commit" \
  --title "Moonlight ${upstream_version} (packaging r${run_number})" \
  --notes-file "$notes_file" \
  --draft
release_created=1

gh release upload "$release_tag" "${assets[@]}" --repo "$GITHUB_REPOSITORY"
release_id=$(gh api "repos/$GITHUB_REPOSITORY/releases/tags/$release_tag" --jq '.id')

local_assets="$temporary_directory/local-assets.tsv"
remote_assets="$temporary_directory/remote-assets.tsv"
for asset in "${assets[@]}"; do
  printf '%s\t%s\tsha256:%s\n' \
    "$(basename -- "$asset")" \
    "$(stat --format=%s "$asset")" \
    "$(sha256sum "$asset" | cut -d ' ' -f 1)"
done | sort >"$local_assets"
gh api --paginate "repos/$GITHUB_REPOSITORY/releases/$release_id/assets?per_page=100" \
  --jq '.[] | [.name, (.size | tostring), (.digest // "")] | @tsv' |
  sort >"$remote_assets"
if ! diff --unified "$local_assets" "$remote_assets"; then
  echo "Uploaded GitHub Release assets failed name, size, or digest verification." >&2
  exit 1
fi

gh api --method PATCH "repos/$GITHUB_REPOSITORY/releases/$release_id" \
  -F draft=false \
  -F prerelease=false \
  -f make_latest=true \
  >/dev/null

python3 scripts/verify-repository-gateway.py \
  "$asset_directory/repository-assets.json" \
  "$REPOSITORY_URL" \
  --cache-bust "$release_tag"

verification_asset_name=$PRODUCTION_VERIFICATION_ASSET
verification_asset="$temporary_directory/$verification_asset_name"
repository_index_sha256=$(sha256sum "$asset_directory/repository-assets.json" | cut -d ' ' -f 1)
jq -n \
  --arg release_tag "$release_tag" \
  --arg repository_url "$REPOSITORY_URL" \
  --arg packaging_commit "$packaging_commit" \
  --arg run_id "$run_id" \
  --arg run_number "$run_number" \
  --arg run_attempt "$run_attempt" \
  --arg repository_index_sha256 "$repository_index_sha256" \
  '{
    schema_version: 1,
    status: "production-repository-gateway-verified",
    release_tag: $release_tag,
    repository_url: $repository_url,
    packaging_commit: $packaging_commit,
    workflow: {
      run_id: $run_id,
      run_number: $run_number,
      run_attempt: $run_attempt
    },
    repository_index: {
      asset_name: "repository-assets.json",
      sha256: $repository_index_sha256
    }
  }' >"$verification_asset"
gh release upload "$release_tag" "$verification_asset" --repo "$GITHUB_REPOSITORY"

expected_verification_asset=$(printf '%s\t%s\tsha256:%s' \
  "$verification_asset_name" \
  "$(stat --format=%s "$verification_asset")" \
  "$(sha256sum "$verification_asset" | cut -d ' ' -f 1)")
remote_verification_asset=$(gh api --paginate \
  "repos/$GITHUB_REPOSITORY/releases/$release_id/assets?per_page=100" \
  --jq ".[] | select(.name == \"$verification_asset_name\") | [.name, (.size | tostring), (.digest // \"\")] | @tsv")
if [[ "$remote_verification_asset" != "$expected_verification_asset" ]]; then
  echo "Production-verification asset failed name, size, or digest verification." >&2
  exit 1
fi

python3 scripts/validate-production-verification.py \
  "$build_metadata" \
  "$verification_asset" \
  --release-tag "$release_tag" \
  --repository-url "$REPOSITORY_URL" \
  --repository-index-digest "sha256:$repository_index_sha256"
production_verified=1

bash scripts/reconcile-release-retention.sh \
  "$release_tag" \
  "$verification_asset_name"

echo "Published and verified $release_tag"
