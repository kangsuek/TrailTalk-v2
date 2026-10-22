// @vitest-environment node
// src/core 비의존 규칙(Spec 4.3)이 실제로 위반을 잡는지 확인한다.
// 위반 샘플을 src/core 아래에 잠깐 만들어 oxlint와 tsc(DOM 없는 tsconfig.core.json)를 돌린다.
import { spawnSync } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, describe, expect, it } from 'vitest'

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const fixtureDir = resolve(webDir, 'src/core/__isolation_fixture__')

function write(name: string, source: string): string {
  mkdirSync(fixtureDir, { recursive: true })
  const path = resolve(fixtureDir, name)
  writeFileSync(path, source)
  return path
}

function run(command: string, args: string[]) {
  const result = spawnSync(command, args, { cwd: webDir, encoding: 'utf8' })
  return { status: result.status, output: `${result.stdout}${result.stderr}` }
}

afterAll(() => rmSync(fixtureDir, { recursive: true, force: true }))

describe('core 비의존 린트', () => {
  it.each([
    ['브라우저 전역(window)', 'export const a = window.location\n', 'no-restricted-globals'],
    ['저장소 전역(localStorage)', "export const a = localStorage.getItem('k')\n", 'no-restricted-globals'],
    ['네트워크 전역(fetch)', "export const a = () => fetch('/api')\n", 'no-restricted-globals'],
    ['react import', "import { useState } from 'react'\nexport const a = useState\n", 'no-restricted-imports'],
    ['platform import', "import { x } from '../../platform/x.ts'\nexport const a = x\n", 'no-restricted-imports'],
  ])('oxlint가 %s을 막는다', (_name, source, rule) => {
    const path = write('bad.ts', source)
    const { status, output } = run('npx', ['oxlint', path])
    expect(status).not.toBe(0)
    expect(output).toContain(rule)
  })

  it('oxlint는 core 밖에서는 같은 코드를 막지 않는다', () => {
    const outside = resolve(webDir, 'src/__isolation_outside__.ts')
    writeFileSync(outside, 'export const a = window.location\n')
    try {
      const { status } = run('npx', ['oxlint', outside])
      expect(status).toBe(0)
    } finally {
      rmSync(outside, { force: true })
    }
  })

  it('tsc(DOM 없음)가 DOM·타이머 전역을 막는다', () => {
    write('dom.ts', 'export const a = document.title\nexport const t = setTimeout(() => {}, 1)\n')
    const { status, output } = run('npx', ['tsc', '-p', 'tsconfig.core.json'])
    expect(status).not.toBe(0)
    expect(output).toContain("Cannot find name 'document'")
    expect(output).toContain("Cannot find name 'setTimeout'")
  })

  it('정상 core 코드는 둘 다 통과한다', () => {
    rmSync(fixtureDir, { recursive: true, force: true })
    const path = write('good.ts', 'export const add = (a: number, b: number): number => a + b\n')
    expect(run('npx', ['oxlint', path]).status).toBe(0)
    expect(run('npx', ['tsc', '-p', 'tsconfig.core.json']).status).toBe(0)
  })
})
