/**
 * dsh-creative-studio — DeepSeek Harness plugin entry.
 *
 * Registers both bundled skills (image-studio, video-studio) with the host skill
 * registry, so the pack ships as a normal DSH plugin instead of relying on files
 * placed in the user-level skills root. The heavy lifting lives in ./toolkit/cs.py,
 * which the agent invokes through the shell.
 *
 * IMPORTANT — module shape constraints:
 *   The host loads profile bundles through a CommonJS-compatible path
 *   (`require()` succeeds on the first-party plugins, e.g. dsh-univer-office).
 *   A module with *top-level await* becomes an async ESM graph, and that load then
 *   fails with ERR_REQUIRE_ASYNC_MODULE — the plugin silently never registers.
 *   Keep this file TLA-free: static imports only, and any optional dynamic import
 *   must happen inside an async function.
 *
 * Contract mirrors first-party plugins: `inject = ['skills']` plus
 * `ctx.skills.registerProvider(() => provider)`, where the provider exposes
 * `name`, `list()` and `get(candidate)`; every candidate carries a finite numeric
 * `rank`.
 */
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

export const name = 'dsh-creative-studio'
export const inject = ['skills']

const PROVIDER_NAME = 'creative-studio'
const INVOCATION = { modelInvocable: true, userInvocable: true }

/**
 * Host precedence rank. Pinned from @deepseek-ai/dsh-skill (lib/index.js:23
 * `const BUNDLED_SKILL_RANK = 600`), the documented value for packaged providers;
 * the registry rejects candidates whose rank is missing or not a finite number.
 * `resolveRank()` opportunistically reads the host constant at list() time without
 * introducing top-level await.
 */
const DEFAULT_RANK = 600

/** Skills shipped inside this package (directory name === skill name). */
const SKILL_DIRS = ['image-studio', 'video-studio']

const PACKAGE_ROOT = new URL('../', import.meta.url)

let rankPromise = null

function resolveRank() {
  rankPromise ??= (async () => {
    try {
      const mod = await import('@deepseek-ai/dsh-skill')
      if (typeof mod?.BUNDLED_SKILL_RANK === 'number') return mod.BUNDLED_SKILL_RANK
    } catch {
      // Host package not resolvable from this path — fall back to the pinned value.
    }
    return DEFAULT_RANK
  })()
  return rankPromise
}

function skillFileUrl(dir) {
  return new URL(`../skills/${dir}/SKILL.md`, import.meta.url)
}

function skillResourceBase(dir) {
  return {
    kind: 'directory',
    path: fileURLToPath(new URL(`../skills/${dir}/`, import.meta.url)),
  }
}

/** Minimal frontmatter reader: enough for `name:`, `description:` and `whenToUse:`. */
function parseFrontmatter(text) {
  if (!text.startsWith('---')) return { data: {}, body: text }
  const end = text.indexOf('\n---', 3)
  if (end === -1) return { data: {}, body: text }
  const head = text.slice(3, end)
  const body = text.slice(text.indexOf('\n', end + 1) + 1)
  const data = {}
  for (const rawLine of head.split('\n')) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const idx = line.indexOf(':')
    if (idx === -1) continue
    const key = line.slice(0, idx).trim()
    let value = line.slice(idx + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    data[key] = value
  }
  return { data, body }
}

async function readSkill(dir, rank) {
  const locator = skillFileUrl(dir)
  const text = await readFile(locator, 'utf8')
  const { data, body } = parseFrontmatter(text)
  return {
    name: data.name || dir,
    description: data.description || `Bundled skill ${dir}`,
    ...(data.whenToUse ? { whenToUse: data.whenToUse } : {}),
    invocation: INVOCATION,
    provider: PROVIDER_NAME,
    source: 'bundled',
    rank,
    resourceBase: skillResourceBase(dir),
    locator,
    body,
  }
}

const provider = {
  name: PROVIDER_NAME,
  async list() {
    const rank = await resolveRank()
    const out = []
    for (const dir of SKILL_DIRS) {
      try {
        const { body, ...candidate } = await readSkill(dir, rank)
        out.push(candidate)
      } catch (error) {
        // A missing or unreadable skill must not take the host down.
        console.warn(`[dsh-creative-studio] cannot list skill "${dir}": ${error?.message ?? error}`)
      }
    }
    return out
  },
  async get(candidate) {
    if (!(candidate?.locator instanceof URL)) {
      throw new Error('dsh-creative-studio skill locator must be a URL')
    }
    const text = await readFile(candidate.locator, 'utf8')
    const { body } = parseFrontmatter(text)
    const { body: _ignored, ...meta } = candidate
    return { ...meta, content: body }
  },
}

export function apply(ctx) {
  try {
    ctx.skills.registerProvider(() => provider)
  } catch (error) {
    console.warn(`[dsh-creative-studio] skill provider registration failed: ${error?.message ?? error}`)
  }
}

/** Exported for the standalone contract test (scripts/provider-selftest.mjs). */
export const __provider = provider
export const __packageRoot = PACKAGE_ROOT

export default { name, inject, apply }
