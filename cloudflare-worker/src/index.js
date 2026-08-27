const GITHUB_RELEASE_BASE =
  "https://github.com/aldobarr/moonlight-vplus-flatpak/releases/download/";
const DOWNLOAD_PATH =
  /^\/download\/([0-9A-Za-z][0-9A-Za-z._+-]*)\/([0-9A-Za-z][0-9A-Za-z._+-]*)$/;

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

export default {
  async fetch(request) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return plainText("Method Not Allowed\n", 405, { Allow: "GET, HEAD" });
    }

    const download = releaseDownload(new URL(request.url).pathname);
    if (download === null) {
      return plainText(request.method === "HEAD" ? null : "Not Found\n", 404);
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
