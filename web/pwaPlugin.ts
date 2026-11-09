import { createHash } from 'node:crypto'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import type { Plugin } from 'vite'

// 서비스 워커(sw/sw.js)에 미리 저장할 파일 목록과 버전을 채워 dist/sw.js로 내는 빌드 플러그인(M6, PWA).
// 번들(index.html·해시 이름 js/css)과 public 폴더(아이콘·매니페스트·favicon)를 미리 저장하고,
// 큰 음성 모델(dist/vad/)은 처음 쓸 때 저장한다(sw.js의 cacheFirst). 버전은 미리 저장할 파일 내용의 해시라
// 앱이 바뀌면 sw.js 내용이 달라져 브라우저가 새 워커를 설치하고 "새 버전 적용"이 나타난다.

const SW_SOURCE = join(import.meta.dirname, 'sw', 'sw.js')

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
}

export function pwa(): Plugin {
  let publicDir = ''
  return {
    name: 'trailtalk-pwa',
    apply: 'build',
    configResolved(config) {
      publicDir = config.publicDir
    },
    // index.html은 Vite의 html 플러그인이 generateBundle에서 내므로 그 뒤에 실행해야 목록에 들어간다
    generateBundle: {
      order: 'post',
      handler(_options, bundle) {
        const entries = new Map<string, string>() // 주소 → 내용 해시
        const hash = (data: string | Uint8Array) => createHash('sha256').update(data).digest('hex')
        for (const [fileName, item] of Object.entries(bundle)) {
          if (fileName.startsWith('vad/')) continue
          entries.set(`/${fileName}`, hash(item.type === 'chunk' ? item.code : item.source))
        }
        for (const path of walk(publicDir)) {
          const name = relative(publicDir, path).split('\\').join('/')
          if (name === 'sw.js') continue
          entries.set(`/${name}`, hash(readFileSync(path)))
        }
        const urls = [...entries.keys()].sort()
        const version = hash(urls.map((url) => `${url}:${entries.get(url)}`).join('\n')).slice(
          0,
          12,
        )
        const source = readFileSync(SW_SOURCE, 'utf8')
          .replace('__VERSION__', version)
          .replace('__PRECACHE__', JSON.stringify(urls, null, 2))
        this.emitFile({ type: 'asset', fileName: 'sw.js', source })
      },
    },
  }
}
