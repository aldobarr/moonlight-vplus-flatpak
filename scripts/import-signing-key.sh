#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 GNUPG_HOME PUBLIC_KEY" >&2
  exit 2
fi
: "${FLATPAK_GPG_PRIVATE_KEY_B64:?FLATPAK_GPG_PRIVATE_KEY_B64 is required}"

export GNUPGHOME=$1
public_key=$2
if [[ ! -f "$public_key" ]]; then
  echo "Committed repository public key is missing: $public_key" >&2
  exit 1
fi

install -d -m 700 "$GNUPGHOME"
printf '%s' "$FLATPAK_GPG_PRIVATE_KEY_B64" |
  base64 --decode |
  gpg --batch --import

mapfile -t fingerprints < <(
  gpg --batch --with-colons --list-secret-keys |
    awk -F: '$1 == "sec" { primary = 1; next } primary && $1 == "fpr" { print $10; primary = 0 }'
)
if [[ ${#fingerprints[@]} -ne 1 || ! ${fingerprints[0]} =~ ^[0-9A-F]{40}$ ]]; then
  echo "The signing secret must contain exactly one primary OpenPGP key." >&2
  exit 1
fi
fingerprint=${fingerprints[0]}

exported_public_key=$(mktemp "$GNUPGHOME/exported-public-key.XXXXXX")
gpg --batch --export "$fingerprint" >"$exported_public_key"
if ! cmp --silent "$public_key" "$exported_public_key"; then
  echo "The signing secret does not match the committed public key." >&2
  exit 1
fi
rm -- "$exported_public_key"

printf '%s\n' "$fingerprint"
