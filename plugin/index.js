/**
 * SPDX-License-Identifier: BSD-3-Clause
 * License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
 */

import { execFile } from "node:child_process"
import { createHash } from "node:crypto"
import { readFile } from "node:fs/promises"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { promisify } from "node:util"
import { registerSearch } from "../payload/.opencode/search/registration.js"

const home = dirname(fileURLToPath(import.meta.url))
const run = promisify(execFile)
const quote = (value) => "'" + value.replaceAll("'", "'\\''") + "'"

async function optionalJSON(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"))
  } catch (error) {
    if (error.code === "ENOENT") return undefined
    throw error
  }
}

export default {
  id: "opencode-repo-search",
  async setup(ctx) {
    const version = /^v?(\d+)\.(\d+)\.(\d+)/.exec(ctx.app.version)
    if (!version || Number(version[1]) !== 2 ||
        (Number(version[2]) === 0 && Number(version[3]) < 15)) {
      throw new Error("repo-search requires OpenCode V2 >=2.0.15 and <3")
    }
    let root = ctx.location.directory
    try {
      root = (await run("git", ["-C", root, "rev-parse", "--show-toplevel"])).stdout.trim()
    } catch {
      // Global installation also loads at non-Git locations; init explains the requirement.
    }
    // Existing copied installations own their registrations until explicitly migrated.
    for (const layout of ["search-local", "search"]) {
      if (await optionalJSON(join(root, ".opencode", layout, "install.json"))) return
    }
    const directory = join(root, ".opencode/search-package")
    const launcher = ["uv", "run", "--no-project", "--isolated", "--no-config", "--python", "3.12", "python",
      join(home, "launch.py")]
    let state, signature, closed = false
    const refresh = async () => {
      const settings = await optionalJSON(join(directory, "runtime.json"))
      const profile = settings && await optionalJSON(join(root, settings.profile))
      const next = JSON.stringify([settings, profile])
      if (next === signature) return false
      if (closed) return false
      const revision = createHash("sha256").update(next).digest("hex")
      state = settings && profile ? {
        root, profile, runtimeLabel: launcher.map(quote).join(" "),
        command: (task, corpus) => [...launcher, task, "--root", root,
          "--configuration-revision", revision, "--corpus", corpus],
      } : undefined
      signature = next
      return true
    }
    await refresh()
    const guide = join(home, "../payload/docs/agent-search.md")
    await registerSearch(ctx, {
      getState: () => state,
      skillPath: join(home, "../payload/.claude/skills/repo-knowledge-search/SKILL.md"),
      instruction: (task, arguments_) =>
        `Read ${JSON.stringify(guide)}. Package launcher: ${launcher.map(quote).join(" ")}. ` +
        `Run ${task} --root ${quote(root)} with caller arguments: ${JSON.stringify(arguments_)}. ` +
        "No init action means report choices only. Only an explicit git-commit action " +
        "authorizes staging/committing; git-ignore uses local Git excludes. " +
        "For status/sync inspect each enabled corpus with --corpus NAME unless selected. " +
        "Report policy provenance, source commit, integrity and currency.",
    })
    let pending = false
    const timer = setInterval(async () => {
      if (pending) return
      pending = true
      try {
        if (await refresh() && !closed) await ctx.mcp.reload()
      } catch (error) {
        console.error("repo-search: configuration reload failed:", error.message)
      } finally {
        pending = false
      }
    }, 2000)
    timer.unref?.()
    return () => { closed = true; clearInterval(timer) }
  },
}
