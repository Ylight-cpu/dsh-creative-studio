/**
 * Standalone contract test for the plugin's skill provider.
 *
 * The assertions mirror the host validator (`@deepseek-ai/dsh-skill`
 * `validateCandidate` / `validateDefinition`) field by field, so a provider that
 * passes here will not be rejected by the registry at runtime — including the
 * `rank` requirement that a finite number must be present on every candidate.
 *
 *   node scripts/provider-selftest.mjs
 */
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { apply as applyPlugin, inject, name } from '../lib/index.js'

const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/ // host: SKILL_NAME
const PROVIDER_NAME = 'creative-studio'
/**
 * Pinned from the host package (@deepseek-ai/dsh-skill lib/index.js:23
 * `const BUNDLED_SKILL_RANK = 600`). ESM resolves bare specifiers relative to the
 * importing file, so when this pack is linked into a profile the host package is
 * not reachable from here — the pinned value is what actually ships.
 */
const EXPECTED_RANK = 600

let officialRank = null
try {
  const mod = await import('@deepseek-ai/dsh-skill')
  officialRank = typeof mod?.BUNDLED_SKILL_RANK === 'number' ? mod.BUNDLED_SKILL_RANK : null
} catch {
  officialRank = null
}

// ---------- plugin surface ----------
let registered = null
applyPlugin({ skills: { registerProvider(factory) { registered = factory } } })
assert.equal(name, 'dsh-creative-studio', 'plugin name')
assert.deepEqual(inject, ['skills'], 'plugin must inject the skills service')
assert.equal(typeof registered, 'function', 'registerProvider must be called during apply')

const provider = registered()
assert.equal(provider.name, PROVIDER_NAME, 'provider name')

// ---------- candidates ----------
const candidates = await provider.list()
assert.ok(Array.isArray(candidates) && candidates.length >= 2, `expected >=2 skills, got ${candidates.length}`)

const skills = []
for (const candidate of candidates) {
  const where = `skill "${candidate?.name}"`

  // mirrors validateCandidate()
  assert.equal(typeof candidate.name, 'string', `${where}: name must be a string`)
  assert.ok(SKILL_NAME.test(candidate.name), `${where}: name fails the host SKILL_NAME pattern`)
  assert.equal(typeof candidate.description, 'string', `${where}: description must be a string`)
  assert.ok(candidate.description.length > 40, `${where}: description looks too short to trigger reliably`)
  assert.equal(typeof candidate.invocation, 'object', `${where}: invocation must be an object`)
  assert.equal(typeof candidate.invocation.modelInvocable, 'boolean', `${where}: invocation.modelInvocable must be boolean`)
  assert.equal(typeof candidate.invocation.userInvocable, 'boolean', `${where}: invocation.userInvocable must be boolean`)
  assert.equal(typeof candidate.source, 'string', `${where}: source must be a string`)
  assert.ok(candidate.source.length > 0, `${where}: source must not be empty`)
  assert.equal(typeof candidate.rank, 'number', `${where}: rank must be a number`)
  assert.ok(Number.isFinite(candidate.rank), `${where}: rank must be finite`)
  assert.equal(typeof candidate.provider, 'string', `${where}: provider must be a string`)
  assert.equal(candidate.provider, provider.name, `${where}: provider must equal the provider name`)
  if (candidate.whenToUse !== undefined) assert.equal(typeof candidate.whenToUse, 'string', `${where}: whenToUse must be a string`)
  if (candidate.path !== undefined) assert.equal(typeof candidate.path, 'string', `${where}: path must be a string`)

  // resourceBase must point at a readable directory
  assert.equal(candidate.resourceBase?.kind, 'directory', `${where}: resourceBase.kind must be "directory"`)
  assert.ok(candidate.resourceBase?.path, `${where}: resourceBase.path missing`)
  assert.ok(existsSync(candidate.resourceBase.path), `${where}: resourceBase.path does not exist`)

  // locator must be a URL so get() can read it
  assert.ok(candidate.locator instanceof URL, `${where}: locator must be a URL instance`)

  // ---------- loaded body, mirrors validateDefinition() ----------
  const loaded = await provider.get(candidate)
  assert.equal(typeof loaded.content, 'string', `${where}: content must be a string`)
  assert.ok(loaded.content.length > 200, `${where}: content too short (${loaded.content.length})`)
  assert.ok(!loaded.content.startsWith('---'), `${where}: frontmatter must be stripped from content`)
  for (const field of ['name', 'description', 'source', 'provider']) {
    assert.equal(typeof loaded[field], 'string', `${where}: loaded.${field} must be a string`)
  }
  assert.equal(loaded.name, candidate.name, `${where}: loaded name mismatch`)

  skills.push({
    name: candidate.name,
    rank: candidate.rank,
    descriptionChars: candidate.description.length,
    bodyChars: loaded.content.length,
    resourceBase: candidate.resourceBase.path,
  })
}

if (officialRank !== null) {
  assert.equal(officialRank, EXPECTED_RANK,
    `host BUNDLED_SKILL_RANK changed to ${officialRank}; update the plugin and this test`)
}
for (const skill of skills) {
  assert.equal(skill.rank, EXPECTED_RANK,
    `skill "${skill.name}": rank ${skill.rank} != host BUNDLED_SKILL_RANK ${EXPECTED_RANK}`)
}

console.log(JSON.stringify({
  ok: true,
  provider: provider.name,
  rank: skills[0]?.rank,
  expectedRank: EXPECTED_RANK,
  officialRankSeen: officialRank,
  rankSource: officialRank === null ? 'pinned value (host package not resolvable from this file)' : '@deepseek-ai/dsh-skill',
  skills,
}, null, 2))
