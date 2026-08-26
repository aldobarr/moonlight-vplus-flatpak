#!/usr/bin/env python3

"""Verify every repository file through the production redirect gateway."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


GITHUB_RELEASE_ASSET_BASE = (
    "https://github.com/aldobarr/moonlight-vplus-flatpak/releases/latest/download/"
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def redirect_target(url: str, timeout: int) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "moonlight-vplus-flatpak-gateway-verifier"},
    )
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        if error.code not in (301, 302, 303, 307, 308):
            error.close()
            raise RuntimeError(f"Gateway returned HTTP {error.code} for {url}") from error
        location = error.headers.get("Location")
        error.close()
        if not location:
            raise RuntimeError(f"Gateway redirect has no Location header for {url}") from error
        return urllib.parse.urljoin(url, location)
    raise RuntimeError(f"Gateway proxied content instead of redirecting for {url}")


def verify_entry(
    base_url: str,
    entry: dict,
    cache_bust: str,
    timeout: int,
    asset_base: str,
) -> None:
    relative_path = entry["repository_path"]
    encoded_path = urllib.parse.quote(relative_path, safe="/._+-")
    gateway_url = urllib.parse.urljoin(base_url, encoded_path)
    if cache_bust:
        gateway_url = f"{gateway_url}?release={urllib.parse.quote(cache_bust, safe='._+-')}"

    target = redirect_target(gateway_url, timeout)
    expected_target = urllib.parse.urljoin(asset_base, entry["asset_name"])
    if target != expected_target:
        raise RuntimeError(
            f"Gateway mapped {relative_path} to {target} instead of {expected_target}"
        )

    digest = hashlib.sha256()
    size = 0
    request = urllib.request.Request(
        target,
        headers={"User-Agent": "moonlight-vplus-flatpak-gateway-verifier"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        for block in iter(lambda: response.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)

    if size != entry["size"]:
        raise RuntimeError(
            f"Size mismatch for {relative_path}: expected {entry['size']}, received {size}"
        )
    if digest.hexdigest() != entry["sha256"]:
        raise RuntimeError(f"SHA-256 mismatch for {relative_path}")


def verify_gateway(
    index: dict,
    base_url: str,
    cache_bust: str,
    attempts: int,
    retry_delay: float,
    workers: int,
    timeout: int,
    asset_base: str = GITHUB_RELEASE_ASSET_BASE,
) -> None:
    if not base_url.endswith("/"):
        raise ValueError("Repository base URL must end with a slash")
    if not asset_base.endswith("/"):
        raise ValueError("Release asset base URL must end with a slash")
    entries = index.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Repository asset index contains no files")
    summary = next(
        (entry for entry in entries if entry.get("repository_path") == "summary"),
        None,
    )
    if summary is None:
        raise ValueError("Repository asset index does not contain summary")

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            verify_entry(base_url, summary, cache_bust, timeout, asset_base)
            last_error = None
            break
        except Exception as error:  # The final error is reported after bounded retries.
            last_error = error
            if attempt < attempts:
                time.sleep(retry_delay)
    if last_error is not None:
        raise RuntimeError(f"Latest-release redirect did not converge: {last_error}") from last_error

    remaining = [entry for entry in entries if entry is not summary]
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                verify_entry,
                base_url,
                entry,
                cache_bust,
                timeout,
                asset_base,
            ): entry
            for entry in remaining
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as error:
                errors.append(f"{futures[future]['repository_path']}: {error}")
    if errors:
        raise RuntimeError("Repository gateway verification failed:\n" + "\n".join(sorted(errors)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("index", type=Path)
    parser.add_argument("base_url")
    parser.add_argument("--cache-bust", default="")
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--retry-delay", type=float, default=5)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    index = json.loads(args.index.read_text(encoding="utf-8"))
    verify_gateway(
        index,
        args.base_url,
        args.cache_bust,
        args.attempts,
        args.retry_delay,
        args.workers,
        args.timeout,
    )
    print(f"Verified {index['repository_file_count']} repository files through the gateway")


if __name__ == "__main__":
    main()
