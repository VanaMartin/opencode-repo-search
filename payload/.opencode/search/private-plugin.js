/**
 * SPDX-License-Identifier: BSD-3-Clause
 * License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
 */

import { readFile } from "node:fs/promises"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

export default {
  id: "repo-search-private",
  async setup(ctx) {
    const home = dirname(fileURLToPath(import.meta.url))
    const settings = JSON.parse(await readFile(join(home, "runtime.json"), "utf8"))
    const profile = JSON.parse(await readFile(join(home, "profiles.json"), "utf8"))
    const root = ctx.location.directory
    const command = (corpus) => {
      const args = ["uv", "run", "--project", home, "--python", "3.12", "--frozen",
        "python", join(home, "run.py"), "mcp", "--root", root, "--corpus", corpus,
        "--remote", settings.remote, "--branch", settings.branch]
      if (settings.db) args.push("--db", settings.db)
      return args
    }
    await ctx.mcp.transform((editor) => {
      for (const [name, policy] of Object.entries(profile.corpora)) {
        if (policy.enabled) editor.set(policy.server, {
          type: "local", cwd: root, command: command(name), timeout: { startup: 900000 },
        })
      }
    })
    const skill = await readFile(join(home, "guidance/SKILL.md"), "utf8")
    await ctx.skill.transform((editor) => {
      editor.add({
        id: "repo-knowledge-search", name: "repo-knowledge-search",
        description: "Committed-source discovery, reference search, provenance and local delta resolution",
        path: join(home, "guidance/SKILL.md"), content: skill,
      })
    })
    await ctx.command.transform((editor) => {
      for (const [name, description, task] of [
        ["search-init", "Choose git-ignore or git-commit for repository search", "init"],
        ["search-status", "Inspect repository search freshness and runtime", "status"],
        ["search-sync", "Refresh repository search from committed upstream source", "sync"],
      ]) {
        editor.add({ name, description, execute: async ({ sessionID, prompt, delivery }) => {
          await ctx.session.prompt({ ...prompt, sessionID, delivery,
            text: `Read ${JSON.stringify(join(home, "guidance/agent-search.md"))}. ` +
              `Use the installed runtime ${JSON.stringify(join(home, "run.py"))} with uv ` +
              `--project ${JSON.stringify(home)} --python 3.12 --frozen. ` +
              `Run ${task} with these caller arguments: ${JSON.stringify(prompt.text)}. ` +
              "For init, no argument means report choices only. Only the literal git-commit " +
              "action authorizes a local commit; git-ignore uses local Git excludes. " +
              "For status or sync, inspect each enabled corpus with --corpus NAME unless the " +
              "caller selects one. Report policy provenance, source commit and freshness.",
          })
        } })
      }
    })
    await ctx.session.hook("context", (event) => {
      event.system.push({ type: "text", text:
        `Use repo-knowledge-search for conceptual discovery. Runtime: ${home}. ` +
        "Search source is a committed upstream snapshot; policy may be local and hashed. " +
        "Resolve current anchors and branch/staged/dirty/untracked deltas before editing. " +
        "Report source commit, policy provenance, integrity and currency separately.",
      })
    })
    await ctx.session.hook("compaction", (event) => {
      event.system.push({ type: "text", text:
        "Preserve search runtime path, corpus, source commit, policy provenance, integrity, " +
        "currency and unresolved local deltas in the checkpoint when relevant.",
      })
    })
  },
}
