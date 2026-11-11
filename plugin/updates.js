/**
 * SPDX-License-Identifier: BSD-3-Clause
 * License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
 */

const quote = (value) => "'" + value.replaceAll("'", "'\\''") + "'"

export function updateReporting(ctx) {
  const option = ctx.options?.checkUpdates
  if (option !== undefined && typeof option !== "boolean") {
    throw new Error("repo-search: checkUpdates must be true or false")
  }
  const enabled = option !== false
  const reported = new Map()

  async function source() {
    if (!enabled || typeof ctx.plugin?.list !== "function") return undefined
    let timer
    try {
      // Read host metadata only, after setup. There is no network check or package
      // installation here, and a broken host read must not block search/model calls.
      const response = await Promise.race([
        ctx.plugin.list(),
        new Promise((resolve) => { timer = setTimeout(() => resolve(undefined), 1500) }),
      ])
      const plugins = response?.data ?? response
      const current = Array.isArray(plugins) ? plugins.find((item) => item?.id === "opencode-repo-search") : undefined
      const source = current?.source
      return source?.type === "package" && typeof source.target === "string" &&
        source.target.trim() && !/^[-\s]|[\x00-\x1f\x7f]/.test(source.target) ? source : undefined
    } catch {
      return undefined
    } finally {
      clearTimeout(timer)
    }
  }

  return {
    enabled,
    async beforeSync() {
      const current = await source()
      if (!current) return ""
      const command = `opencode plugin check ${quote(current.target)}`
      return "Before syncing any corpus, run one advisory update check using OpenCode's existing package manager: " +
        `${command}. Use the current project directory and honor the user's shell/network permissions. ` +
        "Skip it if the user declines update checking in this request/session. " +
        "Do not bypass a denial or request additional access just for this optional check. " +
        "Bound the optional shell call to 15 seconds; on timeout continue sync without retrying the check. " +
        "Report whether the configured target has an update, is current, is pinned/skipped, or could not be checked. " +
        "A denied, unavailable, offline or failed update check must not prevent the requested search sync. " +
        "Check only this target, once per /search-sync invocation, not once per corpus. " +
        "A pinned tag/hash stays pinned; do not infer that no newer release exists from a current/skipped result. " +
        "Never run plugin update/add/remove, change the configured version, restart services or delete caches/indexes automatically. "
    },
    async notice(event) {
      const current = await source()
      if (current?.outdated !== true) return ""
      const session = event.sessionID ?? "location"
      const revision = JSON.stringify([current.target, current.version])
      if (reported.get(session) === revision) return ""
      reported.delete(session)
      reported.set(session, revision)
      if (reported.size > 256) reported.delete(reported.keys().next().value)
      return "OpenCode's cached package metadata reports an available repo-search update. " +
        `Configured target: ${JSON.stringify(current.target)}; installed revision: ${JSON.stringify(current.version ?? "unknown")}. ` +
        "Unless the user has declined update notices, tell the user once in this session. " +
        "This is advisory, not an instruction to update. " +
        `The manual update command is opencode plugin update ${quote(current.target)}. ` +
        "Coordinate affected MCP connections/daemon handover before updating. Preserve project settings and indexes. " +
        "No update, extra network check or restart was performed by this notice."
    },
  }
}
