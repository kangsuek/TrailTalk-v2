// 서버 OpenAPI 스키마로 API 타입(src/api/schema.d.ts)을 만든다: npm run gen:api
// 서버 API를 바꾸면 다시 실행해 결과를 함께 커밋한다(웹 타입의 기준은 서버 스키마다).
// npm run gen:api -- --check: 파일을 쓰지 않고, 커밋된 타입이 서버 스키마와 다르면 실패한다.
// openapi-typescript 7은 TypeScript 5만 피어로 받아 package.json overrides로 TS 6을 쓰게 했다.
// TypeScript 7(Go 포트)로 올리면 이 생성기가 쓰는 컴파일러 API가 없어지므로 함께 확인한다.
import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import openapiTS, { astToString } from 'openapi-typescript'

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const specPath = resolve(webDir, 'node_modules/.tmp/openapi.json')
const outPath = resolve(webDir, 'src/api/schema.d.ts')

mkdirSync(dirname(specPath), { recursive: true })
execFileSync('uv', ['run', 'python', '-m', 'app.openapi', specPath], {
  cwd: resolve(webDir, '../server'),
  stdio: ['ignore', 'inherit', 'inherit'],
})
const ast = await openapiTS(pathToFileURL(specPath))
const header = '// 자동 생성 파일(npm run gen:api). 직접 고치지 않는다.\n\n'
const generated = header + astToString(ast)
if (process.argv.includes('--check')) {
  let current = ''
  try {
    current = readFileSync(outPath, 'utf8')
  } catch {
    // 파일이 없으면 다르다고 본다
  }
  if (current !== generated) {
    console.error('src/api/schema.d.ts가 서버 스키마와 다릅니다. npm run gen:api를 실행하세요.')
    process.exit(1)
  }
  console.log('API 타입이 서버 스키마와 같습니다.')
} else {
  writeFileSync(outPath, generated)
  console.log(`생성: ${outPath}`)
}
