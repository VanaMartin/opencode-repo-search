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
const entry = pathToFileURL(resolve(
  process.env.REPO_SEARCH_TEST_ENTRY ?? "plugin/index.js",
))
const plugin = (await import(entry)).default
const { updateReporting } = await import(new URL("./updates.js", entry))
const profile = JSON.parse(await readFile(new URL(
  "../payload/.opencode/search/profiles.json", import.meta.url,
), "utf8"))

assert.equal(plugin.id, "opencode-repo-search")

const packageSource = (extra = {}) => ({
  type: "package", target: "github:VanaMartin/opencode-repo-search#main", version: "revision-a", ...extra,
})
const pluginMetadata = (source) => ({ data: [{ id: plugin.id, source }] })

function context(root) {
  const transforms = {}, hooks = {}, prompts = []
  const callbacks = {}, hookCallbacks = {}
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
        const items = hookCallbacks[name] ??= new Set()
        items.add(callback)
        hooks[name] = async (event) => { for (const item of items) await item(event) }
        return { dispose: async () => {
          items.delete(callback)
          if (!items.size) delete hooks[name]
        } }
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
    assert.equal(commands.size, 6)
    assert.match(skills.get("repo-knowledge-search").content, /committed/i)
    await commands.get("search-init").execute({
      sessionID: "test", prompt: { text: "git-ignore", files: [] }, delivery: "queue",
    })
    assert.equal(ctx.prompts[0].delivery, "queue")
    assert.match(ctx.prompts[0].text, /launch.py/)
    assert.match(ctx.prompts[0].text, /git-ignore/)
    assert.match(ctx.prompts[0].text, /visible "Next steps"/)
    assert.match(ctx.prompts[0].text, /returned next_steps/)
    assert.match(ctx.prompts[0].text, /Do not automatically execute/)
    assert.match(ctx.prompts[0].text, /preview, dry run or failure/)
    await commands.get("search-status").execute({
      sessionID: "test", prompt: { text: "", files: [] }, delivery: "queue",
    })
    assert.doesNotMatch(ctx.prompts[1].text, /visible "Next steps"/)
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
    await ctx.hooks.context(event)
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
    execFileSync("git", ["init", "-q", root])
    await mkdir(join(root, ".opencode/search-local"), { recursive: true })
    await writeFile(join(root, ".opencode/search-local/install.json"), "{}")
    const ctx = context(root)
    ctx.plugin = { list: async () => pluginMetadata(packageSource({ outdated: true })) }
    cleanup = await plugin.setup(ctx)
    assert.deepEqual(Object.keys(ctx.transforms), ["command"])
    const commands = new Map()
    ctx.transforms.command({ add: (value) => commands.set(value.name, value) })
    assert.deepEqual([...commands.keys()], ["search-migrate", "search-corpus-add", "search-corpus-update"])
    assert.deepEqual(Object.keys(ctx.hooks), ["context"]) // Native notices only, not copied reminders.
    const before = { sessionID: "legacy", system: [] }
    await ctx.hooks.context(before)
    assert.equal(before.system.length, 1)
    assert.match(before.system[0].text, /cached package metadata/)
    await commands.get("search-migrate").execute({
      sessionID: "test", prompt: { text: "git-ignore --dry-run", files: [] }, delivery: "steer",
    })
    assert.match(ctx.prompts[0].text, /init --migrate/)
    assert.match(ctx.prompts[0].text, /returned next_steps/)
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
    assert.deepEqual(Object.keys(ctx.hooks), ["context"])
    const after = { sessionID: "adopted", system: [] }
    await ctx.hooks.context(after)
    assert.equal(after.system.length, 1) // Existing shared reminders remain authoritative.
    assert.match(after.system[0].text, /cached package metadata/)
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

test("corpus commands route natural language through reviewed validated edits", async () => {
  const root = await mkdtemp(join(tmpdir(), "repo-search corpus commands "))
  let cleanup
  try {
    const ctx = context(root)
    cleanup = await plugin.setup(ctx)
    const commands = new Map()
    ctx.transforms.command({ add: (value) => commands.set(value.name, value) })
    for (const [name, text] of [
      ["search-corpus-add", "Scientific notes in docs/papers; infer the correct parser"],
      ["search-corpus-update", "Broaden papers to include literature/extra and re-sync --apply"],
    ]) {
      const files = [{ uri: "file:///example/request.md" }]
      await commands.get(name).execute({
        sessionID: "corpora", prompt: { text, files }, delivery: "steer",
      })
      const result = ctx.prompts.at(-1)
      assert.equal(result.delivery, "steer")
      assert.equal(result.sessionID, "corpora")
      assert.deepEqual(result.files, files)
      assert.ok(result.text.includes(JSON.stringify(text)))
      assert.match(result.text, /natural-language corpus/)
      assert.match(result.text, /corpus inspect/)
      assert.match(result.text, /Preview first/)
      assert.match(result.text, /--expect-revision/)
      assert.match(result.text, /--replace-lists/)
      assert.match(result.text, /Never stage, commit, push/)
      assert.match(result.text, /PDF ingestion is not implemented/)
      assert.match(result.text, /private-policy rebuild warning/)
    }
  } finally {
    await cleanup?.()
    await rm(root, { recursive: true, force: true })
  }
})

test("linked locations inherit repository-private settings without retargeting other sessions", async (t) => {
  const base = await realpath(await mkdtemp(join(tmpdir(), "repo-search worktree locations ")))
  const root = join(base, "original"), worker = join(base, "linked worker"), unrelated = join(base, "unrelated")
  const cleanups = []
  try {
    execFileSync("git", ["init", "-q", root])
    execFileSync("git", ["-C", root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
      "commit", "--allow-empty", "-qm", "fixture"])
    execFileSync("git", ["-C", root, "worktree", "add", "-q", "-b", "worker", worker])
    execFileSync("git", ["init", "-q", unrelated])
    const directory = join(root, ".git/repo-search")
    await mkdir(directory, { recursive: true })
    await mkdir(join(root, ".opencode/search-local"), { recursive: true })
    await writeFile(join(root, ".opencode/search-local/install.json"), "{}")
    const sharedProfile = structuredClone(profile)
    await writeFile(join(directory, "package.json"), JSON.stringify({
      format: "repo-search-repository-config-v1", origin_worktree: root,
      settings: { remote: "origin", branch: "main", profile: ".opencode/search-package/profiles.json", policy_source: "local" },
      profile: sharedProfile, installation: { migration: {
        sources: [".opencode/search-local"], servers: ["retired-search"], legacy_hooks: true,
      } },
    }))
    const contexts = []
    for (const location of [root, worker, unrelated]) {
      const ctx = context(location)
      ctx.mcp.list = async () => ({ data: location === unrelated ? [] : [{ name: "lancedb", status: { status: "connected" } }] })
      cleanups.push(await plugin.setup(ctx))
      contexts.push(ctx)
    }
    const definition = (ctx, entries = []) => {
      const servers = new Map(entries)
      ctx.transforms.mcp({ set: (name, value) => servers.set(name, value), remove: (name) => servers.delete(name) })
      return servers
    }
    assert.equal(definition(contexts[0]).get("lancedb").cwd, root)
    assert.equal(definition(contexts[1]).get("lancedb").cwd, worker)
    assert.equal(definition(contexts[0], [["retired-search", {}]]).has("retired-search"), false)
    assert.equal(definition(contexts[1], [["retired-search", { unrelated: true }]]).has("retired-search"), true)
    assert.equal(definition(contexts[2]).size, 0)
    for (const index of [0, 1, 2, 0]) {
      const ctx = contexts[index], commands = new Map()
      ctx.transforms.command({ add: (value) => commands.set(value.name, value) })
      await commands.get("search-status").execute({ sessionID: "moving-session", prompt: { text: "", files: [] }, delivery: "queue" })
      const prompt = ctx.prompts.at(-1).text
      assert.ok(prompt.includes(ctx.location.directory))
      assert.match(prompt, /MCP connection snapshot/)
      assert.match(prompt, /index readiness\/integrity/)
      assert.ok(prompt.includes(index === 2 ? '"source":"none"' : '"source":"repository-private"'))
    }
    assert.equal(definition(contexts[0]).get("lancedb").cwd, root)
    assert.equal(definition(contexts[1]).get("lancedb").cwd, worker)
    const event = { system: [] }
    await contexts[1].hooks.context(event)
    assert.match(event.system[0].text, /"inherited":true/)
    // A worktree-local override changes only that location's registration.
    const local = join(worker, ".opencode/search-package")
    await mkdir(local, { recursive: true })
    const override = structuredClone(sharedProfile)
    override.corpora.repository.server = "worker-search"
    await writeFile(join(local, "profiles.json"), JSON.stringify(override))
    await writeFile(join(local, "runtime.json"), JSON.stringify({ profile: ".opencode/search-package/profiles.json", policy_source: "local" }))
    const deadline = Date.now() + 6000
    while (!contexts[1].reloads() && Date.now() < deadline) await setTimeout(50)
    assert.equal(contexts[1].reloads(), 1)
    assert.deepEqual([...definition(contexts[1]).keys()], ["worker-search"])
    assert.deepEqual([...definition(contexts[0]).keys()], ["lancedb"])
    assert.equal(contexts[0].reloads(), 0)
    const errors = []
    t.mock.method(console, "error", (...args) => { errors.push(args.join(" ")) })
    await writeFile(join(directory, "package.json"), "null")
    const invalidDeadline = Date.now() + 6000
    while (!errors.length && Date.now() < invalidDeadline) await setTimeout(50)
    assert.ok(errors.some((error) => error.includes("Unsupported repository-private")))
    assert.deepEqual([...definition(contexts[0]).keys()], ["lancedb"])
    assert.equal(contexts[0].reloads(), 0) // Invalid data must not silently remove active MCPs.
  } finally {
    await Promise.all(cleanups.map((cleanup) => cleanup()))
    await rm(base, { recursive: true, force: true })
  }
})

test("sync guides one targeted native check, under normal permissions, without installing", async () => {
  const root = await mkdtemp(join(tmpdir(), "repo-search update guidance "))
  let cleanup
  try {
    const ctx = context(root)
    const target = "github:owner/repo#branch's-$(not-a-command)"
    let reads = 0
    ctx.plugin = { list: async () => { reads++; return pluginMetadata(packageSource({ target })) } }
    cleanup = await plugin.setup(ctx)
    assert.equal(reads, 0) // No reentrant plugin reads while the location is activating.
    const commands = new Map()
    ctx.transforms.command({ add: (value) => commands.set(value.name, value) })
    assert.equal(commands.has("search-upgrade"), false)
    for (const name of ["search-init", "search-status", "search-corpus-add", "search-corpus-update"]) {
      await commands.get(name).execute({ sessionID: "updates", prompt: { text: "", files: [] }, delivery: "queue" })
      assert.doesNotMatch(ctx.prompts.at(-1).text, /opencode plugin check/)
    }
    assert.equal(reads, 0)
    for (const text of ["", "--corpus references"]) {
      const files = [{ uri: "file:///request.md" }]
      await commands.get("search-sync").execute({ sessionID: "updates", prompt: { text, files }, delivery: "steer" })
      const result = ctx.prompts.at(-1)
      assert.equal(result.delivery, "steer")
      assert.deepEqual(result.files, files)
      assert.ok(result.text.includes(JSON.stringify(text)))
      assert.ok(result.text.includes(root))
      assert.equal(result.text.split("opencode plugin check").length - 1, 1)
      assert.match(result.text, /once per \/search-sync invocation, not once per corpus/)
      assert.match(result.text, /honor the user's shell\/network permissions/)
      assert.match(result.text, /Skip it if the user declines/)
      assert.match(result.text, /Do not bypass a denial/)
      assert.match(result.text, /15 seconds; on timeout continue sync/)
      assert.match(result.text, /offline or failed update check must not prevent/)
      assert.match(result.text, /pinned tag\/hash stays pinned/)
      assert.match(result.text, /Never run plugin update\/add\/remove/)
      const command = result.text.match(/package manager: (.*?)\. Use/s)[1]
      // Parse the generated command with a real shell; metacharacters stay data.
      const args = execFileSync("sh", ["-c", `set -- ${command}; printf '%s\\n' "$@"`], { encoding: "utf8" })
      assert.deepEqual(args.trim().split("\n"), ["opencode", "plugin", "check", target])
    }
    assert.equal(reads, 2)
    ctx.plugin.list = async () => { throw new Error("metadata unavailable") }
    await commands.get("search-sync").execute({ sessionID: "updates", prompt: { text: "", files: [] }, delivery: "queue" })
    assert.match(ctx.prompts.at(-1).text, /Run sync --root/)
    assert.doesNotMatch(ctx.prompts.at(-1).text, /opencode plugin check/)
  } finally {
    await cleanup?.()
    await rm(root, { recursive: true, force: true })
  }
})

test("startup notices use cached metadata and deduplicate by session and installed revision", async () => {
  const root = await mkdtemp(join(tmpdir(), "repo-search startup notice "))
  let cleanup
  try {
    const ctx = context(root)
    let source = packageSource(), reads = 0
    ctx.options = { checkUpdates: true }
    ctx.plugin = { list: async () => { reads++; return pluginMetadata(source) } }
    cleanup = await plugin.setup(ctx)
    assert.equal(reads, 0)
    const notice = async (sessionID) => {
      const event = { sessionID, system: [] }
      await ctx.hooks.context(event)
      assert.match(event.system[0].text, /not initialized/)
      return event.system.slice(1)
    }
    assert.deepEqual(await notice("first"), [])
    source = packageSource({ outdated: true }) // OpenCode can finish its background check later.
    const parts = await notice("first")
    assert.equal(parts.length, 1)
    assert.match(parts[0].text, /cached package metadata/)
    assert.match(parts[0].text, /Unless the user has declined update notices/)
    assert.match(parts[0].text, /opencode plugin update 'github:VanaMartin\/opencode-repo-search#main'/)
    assert.match(parts[0].text, /No update, extra network check or restart was performed/)
    assert.deepEqual(await notice("first"), [])
    assert.equal((await notice("second")).length, 1)
    source = packageSource({ outdated: true, version: "revision-b" })
    assert.equal((await notice("first")).length, 1)
    assert.deepEqual(await notice("first"), [])
    await cleanup()
    cleanup = undefined
    assert.deepEqual(ctx.hooks, {})
  } finally {
    await cleanup?.()
    await rm(root, { recursive: true, force: true })
  }
})

test("checkUpdates false suppresses sync checks and notices without reading metadata", async () => {
  const root = await mkdtemp(join(tmpdir(), "repo-search update opt out "))
  let cleanup
  try {
    const ctx = context(root)
    ctx.options = { checkUpdates: false }
    ctx.plugin = { list: () => { assert.fail("opt-out must not read plugin metadata") } }
    cleanup = await plugin.setup(ctx)
    const commands = new Map()
    ctx.transforms.command({ add: (value) => commands.set(value.name, value) })
    await commands.get("search-sync").execute({ sessionID: "off", prompt: { text: "", files: [] }, delivery: "queue" })
    assert.match(ctx.prompts[0].text, /Run sync --root/)
    assert.doesNotMatch(ctx.prompts[0].text, /opencode plugin check/)
    const event = { sessionID: "off", system: [] }
    await ctx.hooks.context(event)
    assert.equal(event.system.length, 1)
    assert.doesNotMatch(event.system[0].text, /available repo-search update/)
  } finally {
    await cleanup?.()
    await rm(root, { recursive: true, force: true })
  }
})

test("advisory metadata failures, unsupported APIs and non-package sources are harmless", async () => {
  for (const list of [
    undefined,
    () => { throw new Error("unsupported") },
    async () => { throw new Error("unavailable") },
    async () => undefined,
    async () => ({ data: {} }),
    async () => ({ data: [null] }),
    async () => ({ data: [{ id: "another-plugin", source: packageSource({ outdated: true }) }] }),
    ...[
      { type: "local", path: "/local/plugin", outdated: true }, { type: "builtin" }, { type: "sdk" },
      packageSource({ target: "" }), packageSource({ target: "--all" }), packageSource({ target: "a\nb" }),
    ].map((source) => async () => pluginMetadata(source)),
  ]) {
    const updates = updateReporting({ plugin: { list } })
    assert.equal(await updates.beforeSync(), "")
    assert.equal(await updates.notice({ sessionID: "failure" }), "")
  }
  const updates = updateReporting({ plugin: { list: async () => [
    { id: plugin.id, source: packageSource({ outdated: false }) },
  ] } })
  assert.match(await updates.beforeSync(), /opencode plugin check/)
  assert.equal(await updates.notice({ sessionID: "current" }), "")
})

test("slow metadata reads time out and later calls can recover", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] })
  let reject
  const ctx = { plugin: { list: () => new Promise((resolve, fail) => { reject = fail }) } }
  const updates = updateReporting(ctx)
  const pending = updates.beforeSync()
  t.mock.timers.tick(1500)
  assert.equal(await pending, "")
  reject(new Error("late rejection must be handled"))
  const notice = updates.notice({ sessionID: "slow" })
  t.mock.timers.tick(1500)
  assert.equal(await notice, "")
  ctx.plugin.list = async () => pluginMetadata(packageSource({ outdated: true }))
  assert.match(await updates.beforeSync(), /opencode plugin check/)
  assert.match(await updates.notice({ sessionID: "slow" }), /available repo-search update/)
})

test("update notice deduplication stays bounded and concurrent calls do not duplicate", async () => {
  const updates = updateReporting({ plugin: { list: async () => pluginMetadata(packageSource({ outdated: true })) } })
  const results = await Promise.all([updates.notice({ sessionID: "same" }), updates.notice({ sessionID: "same" })])
  assert.equal(results.filter(Boolean).length, 1)
  for (let index = 0; index < 256; index++) {
    assert.ok(await updates.notice({ sessionID: `session-${index}` }))
  }
  assert.equal(await updates.notice({ sessionID: "session-255" }), "")
  assert.ok(await updates.notice({ sessionID: "same" })) // Oldest entry was evicted.
})

test("checkUpdates rejects non-boolean options before registering anything", async () => {
  for (const value of [null, "false", 0, {}, []]) {
    const ctx = context(process.cwd())
    ctx.options = { checkUpdates: value }
    await assert.rejects(plugin.setup(ctx), /checkUpdates must be true or false/)
    assert.deepEqual(ctx.transforms, {})
    assert.deepEqual(ctx.hooks, {})
  }
})
