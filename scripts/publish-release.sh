#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 RELEASE_ASSET_DIRECTORY UPSTREAM_METADATA STATIC_ASSET_DIRECTORY WORKER_DIRECTORY" >&2
  exit 2
fi
: "${BUNDLE_NAME:?BUNDLE_NAME is required}"
: "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID is required}"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN is required}"
: "${DOWNLOAD_BASE_URL:?DOWNLOAD_BASE_URL is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
: "${GITHUB_RUN_ATTEMPT:?GITHUB_RUN_ATTEMPT is required}"
: "${GITHUB_RUN_NUMBER:?GITHUB_RUN_NUMBER is required}"
: "${GITHUB_SHA:?GITHUB_SHA is required}"
: "${PACKAGING_RELEASE_TAG:?PACKAGING_RELEASE_TAG is required}"
: "${REPOSITORY_URL:?REPOSITORY_URL is required}"

asset_directory=$1
upstream_metadata=$2
static_asset_directory=$3
worker_directory=$4
worker_config="$worker_directory/wrangler.jsonc"
wrangler="$worker_directory/node_modules/.bin/wrangler"
upstream_tag=$(jq -er '.tag' "$upstream_metadata")
upstream_version=$(jq -er '.version' "$upstream_metadata")
upstream_url=$(jq -er '.html_url' "$upstream_metadata")
upstream_prerelease=$(jq -er \
  '.prerelease | if type == "boolean" then tostring else error("prerelease must be a Boolean") end' \
  "$upstream_metadata")
release_tag=$PACKAGING_RELEASE_TAG
expected_release_tag="build-${upstream_tag}-r${GITHUB_RUN_NUMBER}-a${GITHUB_RUN_ATTEMPT}"
bundle="$asset_directory/$BUNDLE_NAME"
download_url="${DOWNLOAD_BASE_URL}${release_tag}/${BUNDLE_NAME}"
temporary_directory=$(mktemp -d "${RUNNER_TEMP:-/tmp}/moonlight-release.XXXXXX")
release_created=false
release_published=false
cloudflare_deployed=false
cloudflare_state_uncertain=false
previous_worker_version=
new_worker_version=

active_worker_version() {
  local output_file=$1

  "$wrangler" deployments status \
    --config "$worker_config" \
    --json >"$output_file" || return 1
  jq -er '
    .versions
    | if length == 1 and .[0].percentage == 100
      then .[0].version_id
      else error("production is not assigned to one Worker version at 100%")
      end
  ' "$output_file"
}

delete_incomplete_release() {
  if gh release delete "$release_tag" \
    --repo "$GITHUB_REPOSITORY" \
    --cleanup-tag \
    --yes \
    >/dev/null; then
    echo "Deleted incomplete release and tag $release_tag." >&2
  else
    echo "Unable to delete incomplete release and tag $release_tag." >&2
  fi
}

cleanup() {
  local status=$?
  local active_version
  local release_state=missing

  trap - EXIT
  if [[ $status -ne 0 && $release_created == true ]]; then
    if release_state=$(gh api \
      "repos/$GITHUB_REPOSITORY/releases/tags/$release_tag" \
      --jq 'if .draft then "draft" else "published" end' 2>/dev/null); then
      if [[ "$release_state" == published ]]; then
        release_published=true
        echo "Preserving $release_tag because it is already published." >&2
      fi
    else
      release_state=unknown
      echo "Unable to determine the state of $release_tag; preserving it." >&2
    fi
  fi

  if [[ \
    $status -ne 0 && \
    $release_state == draft && \
    $cloudflare_deployed == true && \
    $release_published == false \
  ]]; then
    if ! active_version=$(active_worker_version "$temporary_directory/rollback-status.json"); then
      cloudflare_state_uncertain=true
      echo "Unable to confirm the active Worker version; preserving the draft release." >&2
    elif [[ "$active_version" == "$previous_worker_version" ]]; then
      cloudflare_deployed=false
    elif [[ "$active_version" != "$new_worker_version" ]]; then
      cloudflare_state_uncertain=true
      echo "A different Worker version is active; preserving the draft release." >&2
    elif "$wrangler" rollback "$previous_worker_version" \
      --config "$worker_config" \
      --message "Rollback incomplete publication $release_tag" \
      --yes; then
      cloudflare_deployed=false
      echo "Restored Worker version $previous_worker_version." >&2
    else
      echo "Unable to restore Worker version $previous_worker_version; preserving the draft release." >&2
    fi
  fi

  if [[ \
    $status -ne 0 && \
    $release_state == draft && \
    $release_published == false && \
    $cloudflare_deployed == false && \
    $cloudflare_state_uncertain == false \
  ]]; then
    delete_incomplete_release
  fi

  rm -rf -- "$temporary_directory"
  exit "$status"
}
trap cleanup EXIT

for command in base64 find gh jq realpath sha256sum stat; do
  if ! command -v "$command" >/dev/null; then
    echo "Required command is unavailable: $command" >&2
    exit 1
  fi
done
if [[ ! -x "$wrangler" ]]; then
  echo "Wrangler is unavailable: $wrangler" >&2
  exit 1
fi
if [[ ! -d "$asset_directory" || ! -f "$upstream_metadata" ]]; then
  echo "Release assets or upstream metadata are missing." >&2
  exit 1
fi
if [[ "$release_tag" != "$expected_release_tag" ]]; then
  echo "Release tag $release_tag does not match $expected_release_tag." >&2
  exit 1
fi
if [[ ! "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "GITHUB_SHA is not a full commit ID." >&2
  exit 1
fi
if [[ "$REPOSITORY_URL" != https://*/ || "$DOWNLOAD_BASE_URL" != https://*/ ]]; then
  echo "Repository and download base URLs must be HTTPS URLs ending in a slash." >&2
  exit 1
fi
if [[ "$BUNDLE_NAME" != "moonlight-qt-${upstream_tag}-x86_64.flatpak" ]]; then
  echo "Bundle name does not match upstream tag $upstream_tag." >&2
  exit 1
fi

mapfile -d '' release_entries < <(find "$asset_directory" -mindepth 1 -maxdepth 1 -print0)
if [[ ${#release_entries[@]} -ne 1 || "${release_entries[0]}" != "$bundle" ]]; then
  echo "The GitHub Release must contain only $BUNDLE_NAME." >&2
  exit 1
fi
if [[ ! -f "$bundle" || -L "$bundle" ]]; then
  echo "Bundle is not a regular file: $bundle" >&2
  exit 1
fi
if [[ $(stat --format=%s "$bundle") -ge 2147483648 ]]; then
  echo "Bundle exceeds GitHub's 2 GiB per-file limit." >&2
  exit 1
fi

if [[ ! -f "$worker_config" || ! -d "$static_asset_directory/repo" ]]; then
  echo "Worker configuration or generated Flatpak repository is missing." >&2
  exit 1
fi
configured_asset_directory=$(jq -er '.assets.directory' "$worker_config")
if [[ \
  "$(realpath "$worker_directory/$configured_asset_directory")" != \
  "$(realpath "$static_asset_directory")" \
]]; then
  echo "Wrangler is not configured to upload $static_asset_directory." >&2
  exit 1
fi
mapfile -d '' static_root_entries < <(
  find "$static_asset_directory" -mindepth 1 -maxdepth 1 -print0
)
if [[ \
  ${#static_root_entries[@]} -ne 1 || \
  "${static_root_entries[0]}" != "$static_asset_directory/repo" || \
  -L "$static_asset_directory/repo" \
]]; then
  echo "The Cloudflare asset root must contain only the Flatpak repository directory." >&2
  exit 1
fi
for repository_entry in config summary summary.sig; do
  if [[ ! -f "$static_asset_directory/repo/$repository_entry" ]]; then
    echo "Flatpak repository is missing $repository_entry." >&2
    exit 1
  fi
done
if [[ ! -d "$static_asset_directory/repo/objects" ]]; then
  echo "Flatpak repository is missing its objects directory." >&2
  exit 1
fi
unexpected_entry=$(find "$static_asset_directory" \
  -mindepth 1 \
  ! -type d \
  ! -type f \
  -print \
  -quit)
if [[ -n "$unexpected_entry" ]]; then
  echo "Cloudflare assets may contain only regular files and directories: $unexpected_entry" >&2
  exit 1
fi
mapfile -d '' static_files < <(find "$static_asset_directory" -type f -print0)
if [[ ${#static_files[@]} -gt 20000 ]]; then
  echo "Cloudflare Free supports at most 20,000 static asset files per Worker version." >&2
  exit 1
fi
for static_file in "${static_files[@]}"; do
  if [[ $(stat --format=%s "$static_file") -gt 26214400 ]]; then
    echo "Cloudflare static asset exceeds 25 MiB: $static_file" >&2
    exit 1
  fi
done

previous_worker_version=$(active_worker_version "$temporary_directory/previous-deployment.json")
if [[ ! "$previous_worker_version" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "Unable to identify the current Worker version." >&2
  exit 1
fi

release_metadata=$(jq -cn \
  --slurpfile upstream "$upstream_metadata" \
  --arg repository_url "$REPOSITORY_URL" \
  --arg packaging_commit "$GITHUB_SHA" \
  --arg release_tag "$release_tag" \
  '{
    repository_url: $repository_url,
    upstream: $upstream[0],
    packaging: {
      commit: $packaging_commit,
      release_tag: $release_tag
    }
  }')
release_metadata_encoded=$(printf '%s' "$release_metadata" | base64 --wrap=0)
notes_file="$temporary_directory/release-notes.md"
{
  printf 'Automated Flatpak packaging release for upstream Moonlight V+ %s.\n\n' "$upstream_tag"
  printf -- '- Flatpak bundle: %s\n' "$download_url"
  printf -- '- Upstream release: %s\n' "$upstream_url"
  printf -- '- Upstream prerelease: %s\n' "$upstream_prerelease"
  printf -- '- Update origin: %s\n' "$REPOSITORY_URL"
  printf -- '- Packaging commit: %s\n\n' "$GITHUB_SHA"
  printf '<!-- moonlight-flatpak-build-v1:%s -->\n' "$release_metadata_encoded"
} >"$notes_file"

gh release create "$release_tag" \
  --repo "$GITHUB_REPOSITORY" \
  --target "$GITHUB_SHA" \
  --title "Moonlight ${upstream_version} (packaging r${GITHUB_RUN_NUMBER})" \
  --notes-file "$notes_file" \
  --draft
release_created=true

gh release upload "$release_tag" "$bundle" --repo "$GITHUB_REPOSITORY"
release_id=$(gh api "repos/$GITHUB_REPOSITORY/releases/tags/$release_tag" --jq '.id')
local_asset=$(printf '%s\t%s\tsha256:%s' \
  "$BUNDLE_NAME" \
  "$(stat --format=%s "$bundle")" \
  "$(sha256sum "$bundle" | cut -d ' ' -f 1)")
remote_asset=$(gh api "repos/$GITHUB_REPOSITORY/releases/$release_id/assets" \
  --jq 'if length == 1 then .[0] | [.name, (.size | tostring), (.digest // "")] | @tsv else empty end')
if [[ -z "$remote_asset" || "$local_asset" != "$remote_asset" ]]; then
  echo "Uploaded GitHub Release bundle failed name, size, or digest verification." >&2
  exit 1
fi

wrangler_output="$temporary_directory/wrangler-output.ndjson"
WRANGLER_OUTPUT_FILE_PATH="$wrangler_output" \
  "$wrangler" versions upload \
    --config "$worker_config" \
    --message "Flatpak repository for $release_tag"
new_worker_version=$(jq -er \
  'select(.type == "version-upload" and .version == 1) | .version_id' \
  "$wrangler_output" | tail -n 1)
if [[ ! "$new_worker_version" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "Wrangler did not report an uploaded Worker version." >&2
  exit 1
fi

worker_version_before_promotion=$(active_worker_version \
  "$temporary_directory/pre-promotion-deployment.json")
if [[ "$worker_version_before_promotion" != "$previous_worker_version" ]]; then
  echo "The active Worker deployment changed during publication; refusing to overwrite it." >&2
  exit 1
fi

if "$wrangler" versions deploy "${new_worker_version}@100%" \
  --config "$worker_config" \
  --message "Publish $release_tag" \
  --yes; then
  cloudflare_deployed=true
else
  echo "Worker deployment command failed; checking the active version." >&2
  if active_version=$(active_worker_version "$temporary_directory/failed-deployment-status.json"); then
    if [[ "$active_version" == "$new_worker_version" ]]; then
      cloudflare_deployed=true
      echo "Worker version $new_worker_version is active despite the command failure." >&2
    elif [[ "$active_version" != "$previous_worker_version" ]]; then
      cloudflare_state_uncertain=true
    fi
  else
    cloudflare_state_uncertain=true
  fi
  if [[ $cloudflare_deployed == false ]]; then
    exit 1
  fi
fi

gh api --method PATCH "repos/$GITHUB_REPOSITORY/releases/$release_id" \
  -F draft=false \
  -F prerelease=false \
  -f make_latest=true \
  >/dev/null
release_published=true

echo "Published $release_tag with Worker version $new_worker_version"
