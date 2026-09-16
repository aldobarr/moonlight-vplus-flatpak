import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, mkdirSync, statSync, truncateSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import test from "node:test";

test("bulk uploads repository objects larger than the Workers Static Assets limit", () => {
  const directory = mkdtempSync(join(tmpdir(), "moonlight-r2-test-"));
  try {
    const assets = join(directory, "cloudflare-assets");
    const repository = join(assets, "repo");
    const object = join(
      repository,
      "objects",
      "3f",
      "d0a78b827282178cfca471447815b81676587b6ea9a3df2344621941b23193.filez",
    );
    const rclone = join(directory, "rclone");
    const rcloneLog = join(directory, "rclone.log");

    mkdirSync(join(repository, "objects", "3f"), { recursive: true });
    writeFileSync(join(repository, "config"), "config");
    writeFileSync(object, "");
    truncateSync(object, 26_214_401);
    writeFileSync(
      rclone,
      '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "$RCLONE_LOG"\n',
    );
    chmodSync(rclone, 0o755);

    execFileSync(
      "bash",
      [
        "scripts/upload-r2-repository.sh",
        assets,
        "moonlight-vplus-flatpak-repo",
        rclone,
      ],
      {
        cwd: join(import.meta.dirname, "../.."),
        env: {
          ...process.env,
          CLOUDFLARE_ACCOUNT_ID: "account-id",
          CLOUDFLARE_R2_ACCESS_KEY_ID: "access-key",
          CLOUDFLARE_R2_SECRET_ACCESS_KEY: "secret-key",
          RCLONE_LOG: rcloneLog,
        },
        stdio: "pipe",
      },
    );

    assert.equal(statSync(object).size, 26_214_401);
    const log = readFileSync(rcloneLog, "utf8");
    assert.match(
      log,
      /copy .*\/cloudflare-assets\/repo\/objects r2:moonlight-vplus-flatpak-repo\/repo\/objects/,
    );
    assert.match(log, /--transfers 16/);
    assert.match(log, /--header-upload Cache-Control: public, max-age=31536000, immutable/);
    assert.match(log, /--exclude objects\/\*\*/);
    assert.doesNotMatch(log, /r2 object put/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
