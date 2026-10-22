// @vitest-environment node
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { DARK, LIGHT } from '../src/design/tokens.ts'

const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')

function block(selector: string): string {
  const start = css.indexOf(selector)
  expect(start, selector).toBeGreaterThanOrEqual(0)
  return css.slice(start, css.indexOf('}', start))
}

const NAMES = {
  bg: '--bg',
  card: '--card',
  text: '--text',
  textSub: '--text-sub',
  primary: '--primary',
  amber: '--amber',
  brick: '--brick',
} as const

describe('디자인 토큰', () => {
  it.each([
    ['라이트', LIGHT, ':root {'],
    ['다크(시스템)', DARK, ":root:not([data-theme='light']) {"],
    ['다크(수동)', DARK, ":root[data-theme='dark'] {"],
  ])('%s 색이 index.css와 같다', (_name, palette, selector) => {
    const text = block(selector).toLowerCase()
    for (const [key, variable] of Object.entries(NAMES)) {
      const value = palette[key as keyof typeof palette].toLowerCase()
      expect(text, `${selector} ${variable}`).toContain(`${variable}: ${value}`)
    }
  })
})
