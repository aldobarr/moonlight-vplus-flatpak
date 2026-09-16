import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, mkdirSync, statSync, truncateSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import test from "node:test";

test("uploads repository objects larger than the Workers Static Assets limit", () => {
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
    const wrangler = join(directory, "wrangler");
    const wranglerLog = join(directory, "wrangler.log");

    mkdirSync(join(repository, "objects", "3f"), { recursive: true });
    writeFileSync(join(repository, "config"), "config");
    writeFileSync(object, "");
    truncateSync(object, 26_214_401);
    writeFileSync(
      wrangler,
      '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "$WRANGLER_LOG"\n',
    );
    chmodSync(wrangler, 0o755);

    execFileSync(
      "bash",
      [
        "scripts/upload-r2-repository.sh",
        assets,
        "moonlight-vplus-flatpak-repo",
        "releases/v6.4.2",
        wrangler,
      ],
      {
        cwd: join(import.meta.dirname, "../.."),
        env: { ...process.env, WRANGLER_LOG: wranglerLog },
        stdio: "pipe",
      },
    );

    assert.equal(statSync(object).size, 26_214_401);
    const log = readFileSync(wranglerLog, "utf8");
    assert.match(
      log,
      /r2 object put moonlight-vplus-flatpak-repo\/releases\/v6\.4\.2\/repo\/objects\/3f\/d0a78b827282178cfca471447815b81676587b6ea9a3df2344621941b23193\.filez/,
    );
    assert.match(log, /--remote/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
