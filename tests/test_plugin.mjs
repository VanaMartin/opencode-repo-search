/**
 * SPDX-License-Identifier: BSD-3-Clause
 * License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
 */

import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtemp, mkdir, readFile, realpath, rm, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { setTimeout } from "node:timers/promises"
import { pathToFileURL } from "node:url"
import test from "node:test"

// The Python artifact test sets this to the npm-installed entrypoint as well.
const plugin = (await import(pathToFileURL(resolve(
  process.env.REPO_SEARCH_TEST_ENTRY ?? "plugin/index.js",
)))).default
const profile = JSON.parse(await readFile(new URL(
  "../payload/.opencode/search/profiles.json", import.meta.url,
), "utf8"))

assert.equal(plugin.id, "opencode-repo-search")

function context(root) {
  const transforms = {}, hooks = {}, prompts = []
  const callbacks = {}
  let reloads = 0
  const domain = (name) => ({
    transform: async (callback) => {
      const items = callbacks[name] ??= new Set()
      items.add(callback)
      transforms[name] = (editor) => { for (const item of items) item(editor) }
      return { dispose: async () => { items.delete(callback) } }
    },
    reload: async () => { reloads++ },
  })
  return {
    app: { version: "2.0.15" }, location: { directory: root },
    mcp: domain("mcp"), skill: domain("skill"), command: domain("command"),
    session: {
      hook: async (name, callback) => {
        hooks[name] = callback
        return { dispose: async () => { if (hooks[name] === callback) delete hooks[name] } }
      },
      prompt: async (input) => { prompts.push(input) },
    },
    transforms, hooks, prompts, reloads: () => reloads,
  }
}

test("package registers lazily, reloads policy and cleans up its watcher", async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), "repo-search plugin spaces ")))
  let cleanup
  try {
    execFileSync("git", ["init", "-q", root])
    const ctx = context(root)
    cleanup = await plugin.setup(ctx)
    const servers = new Map(), commands = new Map(), skills = new Map()
    ctx.transforms.mcp({ set: (name, value) => servers.set(name, value) })
    assert.equal(servers.size, 0)
    ctx.transforms.command({ add: (value) => commands.set(value.name, value) })
    ctx.transforms.skill({ add: (value) => skills.set(value.id, value) })
    assert.equal(commands.size, 4)
    assert.match(skills.get("repo-knowledge-search").content, /committed/i)
    await commands.get("search-init").execute({
      sessionID: "test", prompt: { text: "git-ignore", files: [] }, delivery: "queue",
    })
    assert.equal(ctx.prompts[0].delivery, "queue")
    assert.match(ctx.prompts[0].text, /launch.py/)
    assert.match(ctx.prompts[0].text, /git-ignore/)
    const directory = join(root, ".opencode/search-package")
    await mkdir(directory, { recursive: true })
    await writeFile(join(directory, "profiles.json"), JSON.stringify(profile))
    await writeFile(join(directory, "runtime.json"), JSON.stringify({
      profile: ".opencode/search-package/profiles.json", policy_source: "local",
    }))
    const deadline = Date.now() + 6000
    while (!ctx.reloads() && Date.now() < deadline) await setTimeout(50)
    assert.equal(ctx.reloads(), 1)
    ctx.transforms.mcp({ set: (name, value) => servers.set(name, value) })
    assert.deepEqual([...servers.keys()], ["lancedb"])
    const server = servers.get("lancedb")
    assert.equal(server.cwd, root)
    assert.ok(server.command.includes(root))
    assert.ok(server.command.includes("--isolated"))
    assert.equal(server.command.at(-1), "repository")
    const event = { system: [] }
    ctx.hooks.context(event)
    assert.match(event.system[0].text, /policy provenance/)
    assert.match(event.system[0].text, /launch.py/)
    const firstCommand = server.command
    profile.corpora.repository.include = ["src/**"]
    await writeFile(join(directory, "profiles.json"), JSON.stringify(profile))
    const changedDeadline = Date.now() + 6000
    while (ctx.reloads() < 2 && Date.now() < changedDeadline) await setTimeout(50)
    assert.equal(ctx.reloads(), 2)
    ctx.transforms.mcp({ set: (name, value) => servers.set(name, value) })
    assert.notDeepEqual(servers.get("lancedb").command, firstCommand)
    await cleanup()
    cleanup = undefined
  } finally {
    await cleanup?.()
    await rm(root, { recursive: true, force: true })
  }
})

test("existing copied integration retains its registrations", async () => {
  const root = await mkdtemp(join(tmpdir(), "repo-search legacy "))
  let cleanup
  try {
    await mkdir(join(root, ".opencode/search-local"), { recursive: true })
    await writeFile(join(root, ".opencode/search-local/install.json"), "{}")
    const ctx = context(root)
    cleanup = await plugin.setup(ctx)
    assert.deepEqual(Object.keys(ctx.transforms), ["command"])
    const commands = new Map()
    ctx.transforms.command({ add: (value) => commands.set(value.name, value) })
    assert.deepEqual([...commands.keys()], ["search-migrate"])
    assert.deepEqual(ctx.hooks, {})
    await commands.get("search-migrate").execute({
      sessionID: "test", prompt: { text: "git-ignore --dry-run", files: [] }, delivery: "steer",
    })
    assert.match(ctx.prompts[0].text, /init --migrate/)
    const directory = join(root, ".opencode/search-package")
    await mkdir(directory, { recursive: true })
    await writeFile(join(directory, "profiles.json"), JSON.stringify(profile))
    await writeFile(join(directory, "runtime.json"), JSON.stringify({
      profile: ".opencode/search-package/profiles.json", policy_source: "local",
    }))
    await writeFile(join(directory, "install.json"), JSON.stringify({ migration: {
      sources: [".opencode/search-local"], servers: ["old-search"], legacy_hooks: true,
    } }))
    const deadline = Date.now() + 6000
    while (!ctx.reloads() && Date.now() < deadline) await setTimeout(50)
    assert.equal(ctx.reloads(), 1)
    const servers = new Map([["old-search", {}]])
    ctx.transforms.mcp({ set: (name, value) => servers.set(name, value),
      remove: (name) => servers.delete(name) })
    assert.deepEqual([...servers.keys()], ["lancedb"])
    assert.deepEqual(ctx.hooks, {}) // One existing shared reminder hook remains authoritative.
  } finally {
    await cleanup?.()
    await rm(root, { recursive: true, force: true })
  }
})

test("unsupported OpenCode API versions fail with a useful message", async () => {
  const ctx = context(process.cwd())
  ctx.app.version = "1.9.0"
  await assert.rejects(plugin.setup(ctx), /OpenCode V2 >=2.0.15/)
})
