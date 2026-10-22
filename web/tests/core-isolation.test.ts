// @vitest-environment node
// src/core 비의존 규칙(Spec 4.3)이 실제로 위반을 잡는지 확인한다.
// 실제 설정(.oxlintrc.json, tsconfig.core.json)을 임시 폴더에 복사하고 거기에 위반 샘플을 만들어
// oxlint와 tsc(DOM 없는 tsconfig)를 돌린다. 저장소의 src/core는 건드리지 않는다.
import { spawnSync } from 'node:child_process'
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, describe, expect, it } from 'vitest'

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const bin = (name: string) => join(webDir, 'node_modules/.bin', name)
const roots: string[] = []

/** 설정을 복사한 임시 작업 폴더에 src/core/<name>.ts를 만든다. */
function sandbox(source: string, name = 'sample.ts') {
  const root = mkdtempSync(join(tmpdir(), 'core-isolation-'))
  roots.push(root)
  mkdirSync(join(root, 'src/core'), { recursive: true })
  copyFileSync(join(webDir, '.oxlintrc.json'), join(root, '.oxlintrc.json'))
  copyFileSync(join(webDir, 'tsconfig.core.json'), join(root, 'tsconfig.core.json'))
  const file = join(root, 'src/core', name)
  writeFileSync(file, source)
  return { root, file }
}

function run(command: string, args: string[], cwd: string) {
  const result = spawnSync(command, args, { cwd, encoding: 'utf8' })
  return { status: result.status, output: `${result.stdout}${result.stderr}` }
}

const oxlint = (root: string, target: string) => run(bin('oxlint'), [target], root)
const tsc = (root: string) => run(bin('tsc'), ['-p', 'tsconfig.core.json'], root)

afterAll(() => {
  for (const root of roots) rmSync(root, { recursive: true, force: true })
})

describe('core 비의존 린트', () => {
  it.each([
    ['window', 'export const a = window.location\n', 'no-restricted-globals'],
    ['globalThis', 'export const a = globalThis\n', 'no-restricted-globals'],
    ['localStorage', "export const a = localStorage.getItem('k')\n", 'no-restricted-globals'],
    ['fetch', "export const a = () => fetch('/api')\n", 'no-restricted-globals'],
    ['setTimeout', 'export const a = setTimeout(() => {}, 1)\n', 'no-restricted-globals'],
    ['react import', "import { useState } from 'react'\nexport const a = useState\n", 'no-restricted-imports'],
    ['react 동적 import', "export const a = () => import('react')\n", 'no-restricted-imports'],
    ['react 재내보내기', "export { useState } from 'react'\n", 'no-restricted-imports'],
    ['require', "const r = require('react')\nexport default r\n", 'no-require-imports'],
    ['platform import', "import { x } from '../platform/x.ts'\nexport const a = x\n", 'no-restricted-imports'],
    ['api import', "import { x } from '../api/health.ts'\nexport const a = x\n", 'no-restricted-imports'],
    ['screens import', "import { x } from '../screens/Main.tsx'\nexport const a = x\n", 'no-restricted-imports'],
  ])('oxlint가 %s을 막는다', (_name, source, rule) => {
    const { root, file } = sandbox(source)
    const { status, output } = oxlint(root, file)
    expect(status).not.toBe(0)
    expect(output).toContain(rule)
  })

  it('oxlint는 core 밖에서는 같은 코드를 막지 않는다', () => {
    const { root } = sandbox('export {}\n')
    mkdirSync(join(root, 'src/platform'), { recursive: true })
    const outside = join(root, 'src/platform/sample.ts')
    writeFileSync(outside, 'export const a = window.location\n')
    expect(oxlint(root, outside).status).toBe(0)
  })

  it('tsc(DOM 없음)가 DOM·타이머 전역을 막는다', () => {
    const { root } = sandbox(
      'export const a = document.title\nexport const t = setTimeout(() => {}, 1)\n',
    )
    const { status, output } = tsc(root)
    expect(status).not.toBe(0)
    expect(output).toContain("Cannot find name 'document'")
    expect(output).toContain("Cannot find name 'setTimeout'")
  })

  it('정상 core 코드는 둘 다 통과한다', () => {
    const { root, file } = sandbox(
      'export const add = (a: number, b: number): number => a + b\n',
    )
    expect(oxlint(root, file).status).toBe(0)
    expect(tsc(root).status).toBe(0)
  })
})
