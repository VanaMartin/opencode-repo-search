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
    const directory = join(root, ".opencode/search-package")
    const launcher = ["uv", "run", "--no-project", "--isolated", "--no-config", "--python", "3.12", "python",
      join(home, "launch.py")]
    const guide = join(home, "../payload/docs/agent-search.md")
    const instruction = (task, arguments_) =>
      `Read ${JSON.stringify(guide)}. Package launcher: ${launcher.map(quote).join(" ")}. ` +
      `Run ${task} --root ${quote(root)} with caller arguments: ${JSON.stringify(arguments_)}. ` +
      "No init action means report choices only. Only an explicit git-commit action " +
      "authorizes staging/committing; git-ignore uses local Git excludes. " +
      "For status/sync inspect each enabled corpus with --corpus NAME unless selected. " +
      "Report policy provenance, source commit, integrity and currency. " +
      "MCP connectivity is separate from index readiness: inspect ready_for_queries and refresh.phase. " +
      (task.startsWith("init") ?
        'After an applied initialization succeeds, show its next message and a visible "Next steps" ' +
        "section containing the returned next_steps, including suggested commands. " +
        "Do not automatically execute those suggestions or push commits. " +
        "For a preview, dry run or failure, do not claim initialization succeeded or show a success checklist." : "")
    const corpusInstruction = (operation, arguments_) =>
      `Read ${JSON.stringify(guide)}, especially Native corpus management. ` +
      `Package launcher: ${launcher.map(quote).join(" ")}. Root: ${quote(root)}. ` +
      `This is a natural-language corpus ${operation} request, not raw CLI arguments: ${JSON.stringify(arguments_)}. ` +
      `First run the launcher corpus inspect --root ${quote(root)} and inspect actual Git/source paths and samples. ` +
      "Infer a proposed corpus entry/patch, never bibliographic facts or page declarations. " +
      "Check current MCP names and choose an unused server name for a new corpus. " +
      "Use reference_note only for Markdown notes with real title/Source/Pagination declarations; " +
      "ordinary extracted paper text uses source, and PDF ingestion is not implemented. " +
      "Use the validated corpus helper with a temporary JSON --spec file outside the worktree. " +
      "Updates append supplied path/extension lists by default; use --replace-lists only for explicitly requested replacement. " +
      "Preserve parser/server identity and unrelated corpora/settings. Only use --exclude-from with explicit approval. " +
      "Preview first, show the concrete changes, selected-file counts, note errors, overlaps and private-policy rebuild warning. " +
      "Unless the caller explicitly requests --apply or confirms the proposal, ask before applying. " +
      "An empty request should ask for purpose/paths (and an existing corpus for update), not invent a selection. " +
      "Apply using --apply --expect-revision from that reviewed preview; stale revisions need a new preview. " +
      "Add --sync only when the caller requests re-syncing; private policy changes can rebuild all enabled corpora. " +
      "Shared policy sync is deferred until publication. Never stage, commit, push or change Git visibility. " +
      "Report applied/preview/failed/deferred state accurately and show returned next_steps."
    await ctx.command.transform((editor) => {
      for (const [name, description, promptText] of [
        ["search-migrate", "Adopt an installer integration into the package",
          (text) => instruction("init --migrate", text)],
        ["search-corpus-add", "Describe and add an independent search corpus",
          (text) => corpusInstruction("add", text)],
        ["search-corpus-update", "Describe corpus changes, broaden paths and optionally re-sync",
          (text) => corpusInstruction("update", text)],
      ]) {
        editor.add({ name, description, execute: async ({ sessionID, prompt, delivery }) => {
          await ctx.session.prompt({ ...prompt, sessionID, delivery, text: promptText(prompt.text) })
        } })
      }
    })
    let state, signature, dispose, hookMode, closed = false
    const refresh = async () => {
      const legacy = []
      for (const layout of ["search-local", "search"]) {
        const path = `.opencode/${layout}`
        if (await optionalJSON(join(root, path, "install.json"))) legacy.push(path)
      }
      const installation = await optionalJSON(join(directory, "install.json"))
      const migration = installation?.migration
      const deferred = legacy.some((path) => !migration?.sources.includes(path))
      const settings = !deferred && await optionalJSON(join(directory, "runtime.json"))
      const profile = settings && await optionalJSON(join(root, settings.profile))
      const next = JSON.stringify([settings, profile, migration, deferred])
      if (next === signature) return false
      if (closed) return false
      const revision = createHash("sha256").update(next).digest("hex")
      state = settings && profile ? {
        root, profile, runtimeLabel: launcher.map(quote).join(" "),
        replacedServers: migration?.servers,
        command: (task, corpus) => [...launcher, task, "--root", root,
          "--configuration-revision", revision, "--corpus", corpus],
      } : undefined
      if (deferred) {
        await dispose?.()
        dispose = undefined
      } else if (!dispose || hookMode !== Boolean(migration?.legacy_hooks)) {
        await dispose?.()
        hookMode = Boolean(migration?.legacy_hooks)
        dispose = await registerSearch(ctx, {
          getState: () => state,
          skillPath: join(home, "../payload/.claude/skills/repo-knowledge-search/SKILL.md"),
          instruction, hooks: !hookMode,
        })
      }
      signature = next
      return true
    }
    await refresh()
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
    return async () => { closed = true; clearInterval(timer); await dispose?.() }
  },
}
