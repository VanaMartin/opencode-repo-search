/**
 * SPDX-License-Identifier: BSD-3-Clause
 * License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
 */

// MCP lifespan owns refresh. This hook keeps source resolution in the agent loop.
export default {
  id: "repo-search",
  async setup(ctx) {
    await ctx.session.hook("context", (event) => {
      event.system.push({
        type: "text",
        text: "For conceptual code/reference discovery use repo-knowledge-search. " +
          "Search hits name a committed upstream snapshot: resolve current anchors, " +
          "read local branch/staged/dirty/untracked deltas, and verify source before edits. " +
          "At handoff report indexed commit, policy provenance, integrity and upstream currency separately.",
      })
    })
    await ctx.session.hook("compaction", (event) => {
      event.system.push({
        type: "text",
        text: "Preserve the search corpus, indexed commit, policy provenance, integrity/currency observations " +
          "and unresolved local source deltas in the checkpoint when relevant.",
      })
    })
  },
}
