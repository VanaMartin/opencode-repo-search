/**
 * SPDX-License-Identifier: BSD-3-Clause
 * License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
 */

import { readFile } from "node:fs/promises"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { registerSearch } from "./registration.js"

export default {
  id: "repo-search-private",
  async setup(ctx) {
    const home = dirname(fileURLToPath(import.meta.url))
    const settings = JSON.parse(await readFile(join(home, "runtime.json"), "utf8"))
    const profile = JSON.parse(await readFile(join(home, "profiles.json"), "utf8"))
    const root = ctx.location.directory
    const command = (task, corpus) => {
      const args = ["uv", "run", "--project", home, "--python", "3.12", "--frozen",
        "python", join(home, "run.py"), task, "--root", root, "--corpus", corpus,
        "--remote", settings.remote, "--branch", settings.branch]
      if (settings.db) args.push("--db", settings.db)
      return args
    }
    await registerSearch(ctx, {
      getState: () => ({ root, profile, command, runtimeLabel: home }),
      skillPath: join(home, "guidance/SKILL.md"),
      instruction: (task, arguments_) =>
        `Read ${JSON.stringify(join(home, "guidance/agent-search.md"))}. ` +
        `Use the installed runtime ${JSON.stringify(join(home, "run.py"))} with uv ` +
        `--project ${JSON.stringify(home)} --python 3.12 --frozen. ` +
        `Run ${task} with these caller arguments: ${JSON.stringify(arguments_)}. ` +
        "For init, no argument means report choices only. Only the literal git-commit " +
        "action authorizes a local commit; git-ignore uses local Git excludes. " +
        "For status or sync, inspect each enabled corpus with --corpus NAME unless the " +
        "caller selects one. Report policy provenance, source commit and freshness.",
    })
  },
}
