import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { build } from 'vite'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

// 실제로 빌드해서 서비스 워커(dist/sw.js)가 오프라인에서 앱이 열리는 데 필요한 파일을 미리 저장하는지 본다.
// (플러그인 순서가 틀려 index.html이 목록에서 빠졌던 문제를 막는다)
let outDir = ''
let sw = ''
let precache: string[] = []

beforeAll(async () => {
  outDir = mkdtempSync(join(tmpdir(), 'trailtalk-pwa-'))
  await build({ logLevel: 'silent', build: { outDir, emptyOutDir: true } })
  sw = readFileSync(join(outDir, 'sw.js'), 'utf8')
  const list = /const PRECACHE = (\[[\s\S]*?\])\n/.exec(sw)
  precache = list ? (JSON.parse(list[1]) as string[]) : []
}, 60_000)

afterAll(() => rmSync(outDir, { recursive: true, force: true }))

describe('서비스 워커 빌드', () => {
  it('앱 껍데기(index.html)와 번들·아이콘·매니페스트를 미리 저장한다', () => {
    expect(precache).toContain('/index.html')
    expect(precache).toContain('/manifest.webmanifest')
    expect(precache).toContain('/favicon.svg')
    expect(precache.some((url) => /^\/assets\/index-.+\.js$/.test(url))).toBe(true)
    expect(precache.some((url) => /^\/assets\/index-.+\.css$/.test(url))).toBe(true)
    expect(precache.filter((url) => url.startsWith('/icons/')).length).toBeGreaterThanOrEqual(3)
  })

  it('미리 저장하는 파일은 모두 실제로 빌드 결과에 있다(없으면 설치가 실패한다)', () => {
    for (const url of precache) expect(existsSync(join(outDir, url)), url).toBe(true)
  })

  it('큰 음성 모델(/vad/)과 sw.js 자신은 미리 저장하지 않는다', () => {
    expect(precache.filter((url) => url.startsWith('/vad/'))).toEqual([])
    expect(precache).not.toContain('/sw.js')
  })

  it('사전 저장은 브라우저 HTTP 캐시를 거치지 않고 서버에서 새로 받는다', () => {
    // 낡은 index.html이 새 버전 캐시에 들어가 이미 사라진 해시 자산을 가리키는 일을 막는다
    expect(sw).toMatch(/new Request\(url, \{ cache: 'reload' \}\)/)
  })

  it('숨김 파일(.DS_Store 등)은 목록에 들어가지 않는다', () => {
    expect(precache.filter((url) => url.split('/').some((part) => part.startsWith('.')))).toEqual(
      [],
    )
  })

  it('템플릿 자리표시자가 남지 않고 버전이 채워진다', () => {
    expect(sw).not.toContain('__VERSION__')
    expect(sw).not.toContain('__PRECACHE__')
    expect(/const VERSION = '[0-9a-f]{12}'/.test(sw)).toBe(true)
  })

  it('앱 매니페스트가 아이콘과 시작 주소를 가진다', () => {
    const manifest = JSON.parse(readFileSync(join(outDir, 'manifest.webmanifest'), 'utf8'))
    expect(manifest.display).toBe('standalone')
    expect(manifest.start_url).toBe('/')
    const purposes = manifest.icons.map((icon: { purpose: string }) => icon.purpose)
    expect(purposes).toContain('any')
    expect(purposes).toContain('maskable')
    for (const icon of manifest.icons) expect(existsSync(join(outDir, icon.src))).toBe(true)
  })
})
