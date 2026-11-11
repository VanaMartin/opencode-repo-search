/**
 * SPDX-License-Identifier: BSD-3-Clause
 * License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
 */

import { execFile } from "node:child_process"
import { createHash } from "node:crypto"
import { lstat, readFile, realpath } from "node:fs/promises"
import { isAbsolute, join, relative, resolve } from "node:path"
import { promisify } from "node:util"

const run = promisify(execFile)
const directory = ".opencode/search-package"
const digest = (raw) => createHash("sha256").update(raw).digest("hex")
const outside = (root, path) => {
  const name = relative(root, path)
  return name === ".." || name.startsWith("../") || isAbsolute(name)
}
export async function optionalJSON(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"))
  } catch (error) {
    if (error.code === "ENOENT") return undefined
    throw error
  }
}

function localPath(root, name) {
  if (typeof name !== "string" || isAbsolute(name) || name.split("/").some((part) => ["..", ".git"].includes(part))) {
    throw new Error("Package profile must be a repository-relative path")
  }
  return join(root, name)
}

export function provenance(configuration) {
  return Object.fromEntries(["root", "common_dir", "source", "scope", "inherited", "path"]
    .map((name) => [name, configuration[name]]))
}

export async function resolveConfiguration(location) {
  let root = resolve(location), common
  try {
    root = await realpath((await run("git", ["-C", root, "rev-parse", "--show-toplevel"])).stdout.trim())
    common = await realpath(resolve(root, (await run("git", ["-C", root, "rev-parse", "--git-common-dir"])).stdout.trim()))
  } catch {
    return { root, common_dir: null, source: "none", scope: null, inherited: false,
      path: null, settings: null, profile: null, installation: {} }
  }
  const sharedPath = join(common, "repo-search/package.json")
  try {
    const target = await realpath(sharedPath)
    if ((await lstat(sharedPath)).isSymbolicLink() || outside(common, target)) {
      throw new Error("Repository search configuration must stay in the Git common directory")
    }
  } catch (error) {
    if (error.code !== "ENOENT") throw error
  }
  const shared = await optionalJSON(sharedPath)
  if (shared !== undefined && (!shared || typeof shared !== "object" ||
      shared.format !== "repo-search-repository-config-v1")) {
    throw new Error("Unsupported repository-private search configuration")
  }
  let path = join(root, directory, "runtime.json")
  const tracked = Boolean((await run("git", ["-C", root, "ls-files", "--", `:(literal)${directory}/runtime.json`])).stdout)
  let settings = !tracked || !shared ? await optionalJSON(path) : undefined
  if (settings !== undefined && (!settings || typeof settings !== "object" || typeof settings.profile !== "string")) {
    throw new Error("Invalid worktree search settings")
  }
  if (settings && shared?.adoptions?.[root]) {
    const binding = shared.adoptions[root]
    if (binding.runtime === digest(await readFile(path)) &&
        binding.profile === digest(await readFile(localPath(root, settings.profile)))) settings = undefined
  }
  let profile, installation = {}, source = "none", scope = null, inherited = false
  if (settings) {
    const profilePath = localPath(root, settings.profile)
    if (outside(root, await realpath(profilePath))) throw new Error("Package settings resolve outside the worktree")
    profile = await optionalJSON(profilePath)
    installation = await optionalJSON(join(root, directory, "install.json")) ?? {}
    source = tracked ? "committed" : "worktree-private"
    scope = "worktree"
  } else if (shared) {
    settings = shared.settings
    profile = shared.profile
    installation = shared.installation ?? {}
    localPath(root, settings.profile)
    source = "repository-private"
    scope = "repository"
    inherited = root !== shared.origin_worktree
    path = sharedPath
  } else path = null
  if (settings && (!profile || profile.format !== "repo-search-profiles-v1" || !profile.corpora)) {
    throw new Error("Invalid search profile; retaining the previous registration")
  }
  return { root, common_dir: common, source, scope, inherited, path,
    settings: settings ?? null, profile: profile ?? null, installation }
}
