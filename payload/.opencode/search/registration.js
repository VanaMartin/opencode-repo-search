/**
 * SPDX-License-Identifier: BSD-3-Clause
 * License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
 */

import { readFile } from "node:fs/promises"

export async function registerSearch(ctx, { getState, skillPath, instruction, hooks = true }) {
  const registrations = []
  const skill = await readFile(skillPath, "utf8")
  registrations.push(await ctx.mcp.transform((editor) => {
    const state = getState()
    for (const name of state?.replacedServers ?? []) editor.remove(name)
    for (const [name, policy] of Object.entries(state?.profile.corpora ?? {})) {
      if (policy.enabled) editor.set(policy.server, {
        type: "local", cwd: state.root, command: state.command("mcp", name),
        timeout: { startup: 900000 },
      })
    }
  }))
  registrations.push(await ctx.skill.transform((editor) => {
    editor.add({
      id: "repo-knowledge-search", name: "repo-knowledge-search",
      description: "Committed-source discovery, reference search, provenance and local delta resolution",
      path: skillPath, content: skill,
    })
  }))
  registrations.push(await ctx.command.transform((editor) => {
    for (const [name, description, task] of [
      ["search-init", "Choose git-ignore or git-commit for repository search", "init"],
      ["search-status", "Inspect repository search freshness and runtime", "status"],
      ["search-sync", "Refresh repository search from committed upstream source", "sync"],
    ]) {
      editor.add({ name, description, execute: async ({ sessionID, prompt, delivery }) => {
        await ctx.session.prompt({ ...prompt, sessionID, delivery,
          text: instruction(task, prompt.text),
        })
      } })
    }
  }))
  if (hooks) registrations.push(await ctx.session.hook("context", (event) => {
    const state = getState()
    event.system.push({ type: "text", text: state ?
      `Use repo-knowledge-search for conceptual discovery. Runtime: ${state.runtimeLabel}. ` +
      "Search source is a committed upstream snapshot; policy may be local and hashed. " +
      "Resolve current anchors and branch/staged/dirty/untracked deltas before editing. " +
      "Report source commit, policy provenance, integrity and currency separately." :
      "Repository search is not initialized here. Use /search-init to inspect the setup choices.",
    })
  }))
  if (hooks) registrations.push(await ctx.session.hook("compaction", (event) => {
    if (getState()) event.system.push({ type: "text", text:
      "Preserve search runtime path, corpus, source commit, policy provenance, integrity, " +
      "currency and unresolved local deltas in the checkpoint when relevant.",
    })
  }))
  return async () => {
    await Promise.all(registrations.map((registration) => registration?.dispose()))
  }
}
