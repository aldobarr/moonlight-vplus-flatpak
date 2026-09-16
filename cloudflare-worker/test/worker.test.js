import assert from "node:assert/strict";
import test from "node:test";

import worker from "../src/index.js";

function objectBody(body, { etag = '"etag"', range, size } = {}) {
  const bytes = new TextEncoder().encode(body);

  return {
    body: new Response(bytes).body,
    httpEtag: etag,
    range,
    size: size ?? bytes.length,
    writeHttpMetadata(headers) {
      headers.set("Content-Type", "application/octet-stream");
    },
  };
}

function repositoryEnv(getObject) {
  const calls = [];

  return {
    env: {
      FLATPAK_REPOSITORY: {
        async get(key, options) {
          calls.push({ key, options });
          return getObject(key, options);
        },
      },
    },
    calls,
  };
}

test("serves repository objects from the same R2 keys as static assets", async () => {
  const { env, calls } = repositoryEnv(() => objectBody("summary"));
  const response = await worker.fetch(
    new Request("https://moonlight.barreras.dev/repo/summary"),
    env,
  );

  assert.equal(response.status, 200);
  assert.equal(await response.text(), "summary");
  assert.equal(calls[0].key, "repo/summary");
  assert.equal(calls[0].options.range, calls[0].options.onlyIf);
});

test("preserves HEAD and ranged-read semantics", async () => {
  const { env: headEnv } = repositoryEnv(() => objectBody("summary"));
  const headResponse = await worker.fetch(
    new Request("https://moonlight.barreras.dev/repo/summary", {
      method: "HEAD",
    }),
    headEnv,
  );

  assert.equal(headResponse.status, 200);
  assert.equal(await headResponse.text(), "");
  assert.equal(headResponse.headers.get("Content-Length"), "7");

  const { env: rangeEnv, calls } = repositoryEnv(() =>
    objectBody("cdef", { range: { offset: 2, length: 4 }, size: 10 }),
  );
  const rangeResponse = await worker.fetch(
    new Request("https://moonlight.barreras.dev/repo/summary", {
      headers: { Range: "bytes=2-5" },
    }),
    rangeEnv,
  );

  assert.equal(rangeResponse.status, 206);
  assert.equal(await rangeResponse.text(), "cdef");
  assert.equal(rangeResponse.headers.get("Content-Range"), "bytes 2-5/10");
  assert.equal(rangeResponse.headers.get("Content-Length"), "4");
  assert.equal(calls[0].options.range.get("Range"), "bytes=2-5");
});

test("keeps release downloads and rejects unknown paths", async () => {
  const { env } = repositoryEnv(() => objectBody("unused"));
  const downloadResponse = await worker.fetch(
    new Request(
      "https://moonlight.barreras.dev/download/v6.4.2/moonlight-qt-v6.4.2-x86_64.flatpak",
    ),
    env,
  );
  assert.equal(downloadResponse.status, 302);
  assert.equal(
    downloadResponse.headers.get("Location"),
    "https://github.com/aldobarr/moonlight-vplus-flatpak/releases/download/v6.4.2/moonlight-qt-v6.4.2-x86_64.flatpak",
  );

  const unknownResponse = await worker.fetch(
    new Request("https://moonlight.barreras.dev/not-repository"),
    env,
  );
  assert.equal(unknownResponse.status, 404);
});
