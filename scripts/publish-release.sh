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
if [[ "$upstream_prerelease" == true ]]; then
  make_latest=false
else
  make_latest=true
fi
release_tag=$PACKAGING_RELEASE_TAG
expected_names=$(python3 scripts/release_protocol.py \
  "$upstream_tag" \
  --run-number "$GITHUB_RUN_NUMBER" \
  --run-attempt "$GITHUB_RUN_ATTEMPT")
expected_release_tag=$(jq -er '.release_tag' <<<"$expected_names")
expected_bundle_name=$(jq -er '.bundle_name' <<<"$expected_names")
bundle="$asset_directory/$BUNDLE_NAME"
download_url="${DOWNLOAD_BASE_URL}${release_tag}/${BUNDLE_NAME}"
temporary_directory=$(mktemp -d "${RUNNER_TEMP:-/tmp}/moonlight-release.XXXXXX")
release_created=false
release_published=false
publication_owns_production=false
cloudflare_state_uncertain=false
previous_deployment_id=
new_deployment_id=
new_worker_version=
rollback_deployment_file="$temporary_directory/rollback-deployment.json"

validate_worker_deployment() {
  local input_file=$1
  local output_file=$2

  jq -er '
    def uuid:
      type == "string"
      and test("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$");
    if (
      (.id | uuid)
      and (.versions | type == "array" and length > 0 and length <= 2)
      and all(
        .versions[];
        (.version_id | uuid)
        and (.percentage | type == "number" and . > 0 and . <= 100)
      )
      and ([.versions[].version_id] | length == (unique | length))
      and ([.versions[].percentage] | add == 100)
    ) then .
    else error("invalid Worker deployment response")
    end
  ' "$input_file" >"$output_file"
}

current_worker_deployment() {
  local output_file=$1
  local raw_output_file="$output_file.raw"

  "$wrangler" deployments status \
    --config "$worker_config" \
    --json >"$raw_output_file" || return 1
  validate_worker_deployment "$raw_output_file" "$output_file"
}

deployment_id() {
  jq -er '.id' "$1"
}

deployment_assignment() {
  jq -cer '[.versions[] | {version_id, percentage}] | sort_by(.version_id)' "$1"
}

worker_deployments() {
  local output_file=$1
  local response_file="$output_file.response"
  local header_file="$temporary_directory/cloudflare-api-header"

  (umask 077; printf 'Authorization: Bearer %s\n' "$CLOUDFLARE_API_TOKEN" >"$header_file")

  curl \
    --fail \
    --silent \
    --show-error \
    --header "@$header_file" \
    "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/workers/scripts/$worker_name/deployments" \
    >"$response_file" || return 1
  jq -er '
    if .success == true and (.result.deployments | type == "array")
      then .result.deployments
      else error("invalid Worker deployment history response")
    end
  ' "$response_file" >"$output_file"
}

restore_worker_deployment() {
  local target_deployment=$1
  local expected_replaced_deployment_id=$2
  local maximum_attempts=4
  local target_file="$temporary_directory/restore-target.json"
  local active_deployment
  local active_deployment_id
  local deployment_history
  local predecessor_deployment
  local predecessor_deployment_id
  local restoration_deployment
  local restoration_deployment_id
  local restoration_deployment_raw
  local restoration_message
  local specification_file
  local target_assignment
  local attempt
  local -a deployment_specifications

  jq -e '.' "$target_deployment" >"$target_file" || return 1
  for ((attempt = 1; attempt <= maximum_attempts; attempt++)); do
    specification_file="$temporary_directory/restore-specifications-$attempt.txt"
    if ! jq -er \
      '.versions[] | "\(.version_id)@\(.percentage)%"' \
      "$target_file" >"$specification_file"; then
      return 1
    fi
    mapfile -t deployment_specifications <"$specification_file"
    if [[ ${#deployment_specifications[@]} -eq 0 ]]; then
      return 1
    fi

    restoration_message="Reconcile incomplete publication $release_tag ($attempt)"
    if ! "$wrangler" versions deploy "${deployment_specifications[@]}" \
      --config "$worker_config" \
      --message "$restoration_message" \
      --yes; then
      echo "Worker reconciliation command failed; inspecting deployment history." >&2
    fi

    deployment_history="$temporary_directory/restore-history-$attempt.json"
    restoration_deployment_raw="$temporary_directory/restoration-$attempt.raw.json"
    restoration_deployment="$temporary_directory/restoration-$attempt.json"
    target_assignment=$(deployment_assignment "$target_file") || return 1
    if ! worker_deployments "$deployment_history" ||
      ! jq -er \
        --arg message "$restoration_message" \
        --argjson assignment "$target_assignment" \
        '
          [
            .[]
            | select(
                ([.versions[] | {version_id, percentage}] | sort_by(.version_id)) == $assignment
                and (.annotations["workers/message"] // "") == $message
              )
          ]
          | if length == 1 then .[0]
            else error("reconciliation does not own exactly one Worker deployment")
            end
        ' "$deployment_history" >"$restoration_deployment_raw" ||
      ! validate_worker_deployment "$restoration_deployment_raw" "$restoration_deployment"; then
      return 1
    fi
    restoration_deployment_id=$(deployment_id "$restoration_deployment") || return 1

    active_deployment="$temporary_directory/restore-active-$attempt.json"
    current_worker_deployment "$active_deployment" || return 1
    active_deployment_id=$(deployment_id "$active_deployment") || return 1
    if [[ "$active_deployment_id" != "$restoration_deployment_id" ]]; then
      echo "A newer Worker deployment superseded reconciliation; leaving it untouched." >&2
      return 0
    fi

    predecessor_deployment="$temporary_directory/restore-predecessor-$attempt.json"
    if ! jq -er \
      --arg deployment_id "$restoration_deployment_id" \
      '
        if length > 1 and .[0].id == $deployment_id then .[1]
        else error("reconciliation is not the latest deployment with a predecessor")
        end
      ' "$deployment_history" >"$predecessor_deployment.raw" ||
      ! validate_worker_deployment "$predecessor_deployment.raw" "$predecessor_deployment"; then
      return 1
    fi
    predecessor_deployment_id=$(deployment_id "$predecessor_deployment") || return 1
    if [[ "$predecessor_deployment_id" == "$expected_replaced_deployment_id" ]]; then
      return 0
    fi

    echo "A concurrent Worker deployment was replaced during reconciliation; restoring its assignment." >&2
    jq -e '.' "$predecessor_deployment" >"$target_file" || return 1
    expected_replaced_deployment_id=$restoration_deployment_id
  done

  return 1
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
  local active_deployment_id
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
    $publication_owns_production == true && \
    $release_published == false \
  ]]; then
    if ! current_worker_deployment "$temporary_directory/rollback-status.json"; then
      cloudflare_state_uncertain=true
      echo "Unable to confirm the active Worker deployment; preserving the draft release." >&2
    elif ! active_deployment_id=$(deployment_id "$temporary_directory/rollback-status.json"); then
      cloudflare_state_uncertain=true
      echo "Unable to identify the active Worker deployment; preserving the draft release." >&2
    elif [[ "$active_deployment_id" != "$new_deployment_id" ]]; then
      publication_owns_production=false
      echo "The publication no longer owns production; leaving the active deployment untouched." >&2
    elif restore_worker_deployment "$rollback_deployment_file" "$new_deployment_id"; then
      publication_owns_production=false
      echo "Restored the Worker deployment that preceded $release_tag." >&2
    else
      cloudflare_state_uncertain=true
      echo "Unable to restore the preceding Worker deployment; preserving the draft release." >&2
    fi
  fi

  if [[ \
    $status -ne 0 && \
    $release_state == draft && \
    $release_published == false && \
    $publication_owns_production == false && \
    $cloudflare_state_uncertain == false \
  ]]; then
    delete_incomplete_release
  fi

  rm -rf -- "$temporary_directory"
  exit "$status"
}
trap cleanup EXIT

for command in base64 curl find gh jq python3 realpath sha256sum stat; do
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
if [[ ! "$CLOUDFLARE_ACCOUNT_ID" =~ ^[0-9a-f]{32}$ ]]; then
  echo "CLOUDFLARE_ACCOUNT_ID is not a valid account ID." >&2
  exit 1
fi
if [[ "$CLOUDFLARE_API_TOKEN" == *$'\n'* || "$CLOUDFLARE_API_TOKEN" == *$'\r'* ]]; then
  echo "CLOUDFLARE_API_TOKEN contains invalid line breaks." >&2
  exit 1
fi
if [[ "$REPOSITORY_URL" != https://*/ || "$DOWNLOAD_BASE_URL" != https://*/ ]]; then
  echo "Repository and download base URLs must be HTTPS URLs ending in a slash." >&2
  exit 1
fi
if [[ "$BUNDLE_NAME" != "$expected_bundle_name" ]]; then
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
worker_name=$(jq -er '.name' "$worker_config")
if [[ ! "$worker_name" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "Wrangler contains an invalid Worker name: $worker_name" >&2
  exit 1
fi
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

previous_deployment="$temporary_directory/previous-deployment.json"
if ! current_worker_deployment "$previous_deployment"; then
  echo "Unable to inspect the current Worker deployment." >&2
  exit 1
fi
previous_deployment_id=$(deployment_id "$previous_deployment")
jq -e '.' "$previous_deployment" >"$rollback_deployment_file"

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
    --tag "$release_tag" \
    --message "Flatpak repository for $release_tag"
new_worker_version=$(jq -er \
  'select(.type == "version-upload" and .version == 1) | .version_id' \
  "$wrangler_output" | tail -n 1)
if [[ ! "$new_worker_version" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "Wrangler did not report an uploaded Worker version." >&2
  exit 1
fi

pre_promotion_deployment="$temporary_directory/pre-promotion-deployment.json"
if ! current_worker_deployment "$pre_promotion_deployment"; then
  echo "Unable to confirm the Worker deployment before promotion." >&2
  exit 1
fi
deployment_id_before_promotion=$(deployment_id "$pre_promotion_deployment")
if [[ "$deployment_id_before_promotion" != "$previous_deployment_id" ]]; then
  echo "The active Worker deployment changed during publication; refusing to overwrite it." >&2
  exit 1
fi

if ! "$wrangler" versions deploy "${new_worker_version}@100%" \
  --config "$worker_config" \
  --message "Publish $release_tag" \
  --yes; then
  echo "Worker deployment command failed; reconciling against deployment history." >&2
fi

deployment_history="$temporary_directory/post-promotion-history.json"
if ! worker_deployments "$deployment_history"; then
  cloudflare_state_uncertain=true
  echo "Unable to inspect Worker deployment history after promotion." >&2
  exit 1
fi

owned_deployment_raw="$temporary_directory/owned-deployment.raw.json"
owned_deployment="$temporary_directory/owned-deployment.json"
if ! jq -er \
  --arg version "$new_worker_version" \
  --arg message "Publish $release_tag" \
  '
    [
      .[]
      | select(
          (.versions | length == 1)
          and .versions[0].version_id == $version
          and .versions[0].percentage == 100
          and (.annotations["workers/message"] // "") == $message
        )
    ]
    | if length == 1 then .[0]
      else error("publication does not own exactly one Worker deployment")
      end
  ' "$deployment_history" >"$owned_deployment_raw" ||
  ! validate_worker_deployment "$owned_deployment_raw" "$owned_deployment"; then
  cloudflare_state_uncertain=true
  echo "Unable to identify the Worker deployment created for $release_tag." >&2
  exit 1
fi
new_deployment_id=$(deployment_id "$owned_deployment")
publication_owns_production=true

post_promotion_deployment="$temporary_directory/post-promotion-deployment.json"
if ! current_worker_deployment "$post_promotion_deployment"; then
  cloudflare_state_uncertain=true
  echo "Unable to confirm the Worker deployment after promotion." >&2
  exit 1
fi
active_deployment_id=$(deployment_id "$post_promotion_deployment")
if [[ "$active_deployment_id" != "$new_deployment_id" ]]; then
  publication_owns_production=false
  echo "A newer Worker deployment superseded $release_tag; refusing to publish it." >&2
  exit 1
fi

predecessor_deployment_raw="$temporary_directory/predecessor-deployment.raw.json"
if ! jq -er \
  --arg deployment_id "$new_deployment_id" \
  '
    if length > 1 and .[0].id == $deployment_id then .[1]
    else error("owned deployment is not the latest deployment with a predecessor")
    end
  ' "$deployment_history" >"$predecessor_deployment_raw" ||
  ! validate_worker_deployment "$predecessor_deployment_raw" "$rollback_deployment_file"; then
  cloudflare_state_uncertain=true
  echo "Unable to identify the Worker deployment that preceded $release_tag." >&2
  exit 1
fi
predecessor_deployment_id=$(deployment_id "$rollback_deployment_file")
if [[ "$predecessor_deployment_id" != "$previous_deployment_id" ]]; then
  echo "Another Worker deployment won the promotion race; restoring it instead of publishing $release_tag." >&2
  exit 1
fi

pre_publication_deployment="$temporary_directory/pre-publication-deployment.json"
if ! current_worker_deployment "$pre_publication_deployment"; then
  cloudflare_state_uncertain=true
  echo "Unable to confirm the active Worker deployment before publishing the release." >&2
  exit 1
fi
deployment_id_before_publication=$(deployment_id "$pre_publication_deployment")
if [[ "$deployment_id_before_publication" != "$new_deployment_id" ]]; then
  publication_owns_production=false
  echo "The publication lost Worker deployment ownership before the GitHub release was published." >&2
  exit 1
fi

if ! gh api --method PATCH "repos/$GITHUB_REPOSITORY/releases/$release_id" \
  -F draft=false \
  -F prerelease="$upstream_prerelease" \
  -f make_latest="$make_latest" \
  >/dev/null; then
  echo "GitHub release publication returned an error; reconciling its state." >&2
  if ! github_release_is_draft=$(gh api \
    "repos/$GITHUB_REPOSITORY/releases/$release_id" \
    --jq '.draft' 2>/dev/null) ||
    [[ "$github_release_is_draft" != false ]]; then
    exit 1
  fi
  echo "$release_tag is published despite the command error; continuing reconciliation." >&2
fi
release_published=true

post_publication_deployment="$temporary_directory/post-publication-deployment.json"
if ! current_worker_deployment "$post_publication_deployment" ||
  ! deployment_id_after_publication=$(deployment_id "$post_publication_deployment") ||
  [[ "$deployment_id_after_publication" != "$new_deployment_id" ]]; then
  echo "Worker deployment ownership changed while the GitHub release was being published." >&2
  if gh api --method PATCH "repos/$GITHUB_REPOSITORY/releases/$release_id" \
    -F draft=true \
    >/dev/null; then
    release_published=false
    echo "Returned $release_tag to draft state because publication was not consistent." >&2
  else
    echo "Unable to return $release_tag to draft state; preserving the published release." >&2
  fi
  exit 1
fi

echo "Published $release_tag with Worker deployment $new_deployment_id"
