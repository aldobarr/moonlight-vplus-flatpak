const REPOSITORY_PREFIX = "/repo/";
const RELEASE_ASSET_BASE =
  "https://github.com/aldobarr/moonlight-vplus-flatpak/releases/latest/download/";
const SAFE_REPOSITORY_PATH = /^[A-Za-z0-9._+/-]+$/;

export async function repositoryAssetName(relativePath) {
  const bytes = new TextEncoder().encode(relativePath);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hexadecimal = Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  return `repo-${hexadecimal}`;
}

export function repositoryPath(pathname) {
  if (!pathname.startsWith(REPOSITORY_PREFIX)) {
    return null;
  }

  const relativePath = pathname.slice(REPOSITORY_PREFIX.length);
  const segments = relativePath.split("/");
  if (
    relativePath.length === 0 ||
    relativePath.includes("%") ||
    relativePath.includes("\\") ||
    !SAFE_REPOSITORY_PATH.test(relativePath) ||
    segments.some((segment) => segment === "" || segment === "." || segment === "..")
  ) {
    return null;
  }
  return relativePath;
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

    const relativePath = repositoryPath(new URL(request.url).pathname);
    if (relativePath === null) {
      return plainText(request.method === "HEAD" ? null : "Not Found\n", 404);
    }

    const assetName = await repositoryAssetName(relativePath);
    return new Response(null, {
      status: 302,
      headers: {
        Location: `${RELEASE_ASSET_BASE}${assetName}`,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  },
};
