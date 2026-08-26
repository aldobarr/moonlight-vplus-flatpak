#!/usr/bin/env node

import { copyFile, lstat, mkdir, readdir } from "node:fs/promises";
import { join, relative, resolve, sep } from "node:path";

import { repositoryAssetName } from "../cloudflare-worker/src/index.js";

const GITHUB_ASSET_LIMIT = 1_000;
const GITHUB_ASSET_SIZE_LIMIT = 2 * 1024 * 1024 * 1024;

async function collectRepositoryFiles(directory) {
  const files = [];
  const entries = await readdir(directory, { withFileTypes: true });
  entries.sort((left, right) =>
    left.name < right.name ? -1 : left.name > right.name ? 1 : 0,
  );

  for (const entry of entries) {
    const source = join(directory, entry.name);
    if (entry.isSymbolicLink()) {
      throw new Error(`Repository must not contain symbolic links: ${source}`);
    }
    if (entry.isDirectory()) {
      files.push(...(await collectRepositoryFiles(source)));
    } else if (entry.isFile()) {
      files.push(source);
    }
  }
  return files;
}

async function stageRepository(repository, output, reservedAssets) {
  let repositoryStatus;
  try {
    repositoryStatus = await lstat(repository);
  } catch {
    throw new Error(`Repository directory does not exist: ${repository}`);
  }
  if (!repositoryStatus.isDirectory()) {
    throw new Error(`Repository directory does not exist: ${repository}`);
  }
  if (
    !Number.isInteger(reservedAssets) ||
    reservedAssets < 1 ||
    reservedAssets >= GITHUB_ASSET_LIMIT
  ) {
    throw new Error("Reserved asset count must be between 1 and 999");
  }

  await mkdir(output, { recursive: true });
  if ((await readdir(output)).length !== 0) {
    throw new Error(`Release asset directory must be empty: ${output}`);
  }

  const files = await collectRepositoryFiles(repository);
  if (files.length + reservedAssets > GITHUB_ASSET_LIMIT) {
    throw new Error(
      `Release would exceed GitHub's 1,000-asset limit: ${files.length} repository files plus ${reservedAssets} reserved assets`,
    );
  }

  const assetNames = new Set();
  for (const source of files) {
    const relativePath = relative(repository, source).split(sep).join("/");
    const assetName = await repositoryAssetName(relativePath);
    if (assetNames.has(assetName)) {
      throw new Error(`Repository asset-name collision for ${relativePath}`);
    }
    assetNames.add(assetName);

    const sourceStatus = await lstat(source);
    if (sourceStatus.size >= GITHUB_ASSET_SIZE_LIMIT) {
      throw new Error(`Repository file exceeds GitHub's per-asset limit: ${relativePath}`);
    }
    await copyFile(source, join(output, assetName));
  }
  return files.length;
}

async function main() {
  const cliArguments = process.argv.slice(2);
  const [repositoryArgument, outputArgument, reservedAssetsOption, reservedAssetsArgument] =
    cliArguments;
  if (
    cliArguments.length !== 4 ||
    !repositoryArgument ||
    !outputArgument ||
    reservedAssetsOption !== "--reserved-assets" ||
    !reservedAssetsArgument
  ) {
    throw new Error(
      "Usage: stage-repository-assets.mjs REPOSITORY OUTPUT --reserved-assets COUNT",
    );
  }

  const reservedAssets = Number(reservedAssetsArgument);
  const repositoryFileCount = await stageRepository(
    resolve(repositoryArgument),
    resolve(outputArgument),
    reservedAssets,
  );
  console.log(`Staged ${repositoryFileCount} repository files`);
}

try {
  await main();
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
}
