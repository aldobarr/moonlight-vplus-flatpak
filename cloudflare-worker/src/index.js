const GITHUB_RELEASE_BASE =
  "https://github.com/aldobarr/moonlight-vplus-flatpak/releases/download/";
const DOWNLOAD_PATH =
  /^\/download\/([0-9A-Za-z][0-9A-Za-z._+-]*)\/([0-9A-Za-z][0-9A-Za-z._+-]*)$/;
const REPOSITORY_PATH = /^\/repo\/(.+)$/;
const REPOSITORY_PREFIX = /^releases\/[0-9A-Za-z][0-9A-Za-z._+-]*$/;

function releaseDownload(pathname) {
  let decodedPath;
  try {
    decodedPath = decodeURIComponent(pathname);
  } catch {
    return null;
  }

  const match = DOWNLOAD_PATH.exec(decodedPath);
  if (match === null) {
    return null;
  }

  return `${GITHUB_RELEASE_BASE}${encodeURIComponent(match[1])}/${encodeURIComponent(match[2])}`;
}

function plainText(body, status, headers = {}) {
  return new Response(body, {
    status,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      ...headers,
    },
  });
}

function repositoryObject(pathname, prefix) {
  let decodedPath;
  try {
    decodedPath = decodeURIComponent(pathname);
  } catch {
    return null;
  }

  const match = REPOSITORY_PATH.exec(decodedPath);
  if (match === null || !REPOSITORY_PREFIX.test(prefix)) {
    return null;
  }

  const relativePath = match[1];
  const pathParts = relativePath.split("/");
  if (
    !/^[0-9A-Za-z._/-]+$/.test(relativePath) ||
    pathParts.some((part) => part === "" || part === "." || part === "..")
  ) {
    return null;
  }

  return {
    key: `${prefix}/repo/${relativePath}`,
    relativePath,
  };
}

function repositoryCacheControl(relativePath) {
  return relativePath.startsWith("objects/")
    ? "public, max-age=31536000, immutable"
    : "no-cache";
}

async function repositoryResponse(request, env, pathname) {
  const repository = repositoryObject(pathname, env.REPOSITORY_PREFIX);
  if (repository === null) {
    return plainText("Not Found\n", 404);
  }

  const object = await env.FLATPAK_REPOSITORY.get(repository.key, {
    onlyIf: request.headers,
    range: request.headers,
  });
  if (object === null) {
    return plainText("Not Found\n", 404);
  }

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("ETag", object.httpEtag);
  headers.set("Accept-Ranges", "bytes");
  headers.set("Cache-Control", repositoryCacheControl(repository.relativePath));
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/octet-stream");
  }

  let status = 200;
  if ("body" in object) {
    if (object.range !== undefined) {
      const { offset, length } = object.range;
      status = 206;
      headers.set(
        "Content-Range",
        `bytes ${offset}-${offset + length - 1}/${object.size}`,
      );
      headers.set("Content-Length", String(length));
    } else {
      headers.set("Content-Length", String(object.size));
    }
  } else {
    status = 412;
  }

  return new Response(request.method === "HEAD" ? undefined : object.body, {
    status,
    headers,
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return plainText("Method Not Allowed\n", 405, { Allow: "GET, HEAD" });
    }

    const download = releaseDownload(new URL(request.url).pathname);
    if (download === null) {
      return repositoryResponse(request, env, new URL(request.url).pathname);
    }

    return new Response(null, {
      status: 302,
      headers: {
        Location: download,
        "Cache-Control": "public, max-age=86400, immutable",
        "X-Content-Type-Options": "nosniff",
      },
    });
  },
};
