/**
 * Cross-platform launcher for the Python toolkit: node scripts/run-toolkit.mjs <args...>
 * Resolves the toolkit venv python (runtime/, then .venv, then system python) and
 * forwards all arguments to toolkit/cs.py.
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')

function pickPython() {
  const candidates = [
    join(root, 'runtime', 'Scripts', 'python.exe'),
    join(root, 'runtime', 'bin', 'python3'),
    join(root, '.venv', 'Scripts', 'python.exe'),
    join(root, '.venv', 'bin', 'python3'),
  ]
  for (const c of candidates) if (existsSync(c)) return c
  return process.platform === 'win32' ? 'python' : 'python3'
}

const python = pickPython()
const cli = join(root, 'toolkit', 'cs.py')
const child = spawn(python, [cli, ...process.argv.slice(2)], { stdio: 'inherit', cwd: process.cwd() })
child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal)
  else process.exit(code ?? 1)
})
