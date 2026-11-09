// TrailTalk 서비스 워커(M6, PWA). 앱 껍데기를 미리 저장해 오프라인에서도 앱이 열리게 하고, 새 버전은
// 자동으로 적용하지 않는다: 새 워커는 대기하다가 설정의 "새 버전 적용" 버튼이 보내는 SKIP_WAITING
// 메시지를 받으면 바뀐다(Spec 8절). 빌드할 때 vite.config의 pwa 플러그인이 아래 두 값을 채운다.
const VERSION = '__VERSION__'
const PRECACHE = __PRECACHE__

const CACHE_PREFIX = 'trailtalk-'
const CACHE = CACHE_PREFIX + VERSION
const SHELL = '/index.html'
// 미리 저장할 때는 Origin 없는 요청으로, 모듈 스크립트는 Origin이 붙은 요청으로 조회한다. 서버가 Vary: Origin을
// 보내면 그대로는 빗나가므로 Vary를 무시한다(같은 주소의 같은 파일이다)
const MATCH = { ignoreVary: true }

self.addEventListener('install', (event) => {
  // skipWaiting을 부르지 않는다. 이미 앱을 쓰는 중이면 새 워커는 대기하고 사용자가 적용 시점을 고른다
  // cache: 'reload' — 브라우저 HTTP 캐시의 낡은 index.html이 새 버전 캐시에 들어가 이미 사라진 해시 자산을
  // 가리키지 않게, 사전 저장은 항상 서버에서 새로 받는다
  const requests = PRECACHE.map((url) => new Request(url, { cache: 'reload' }))
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(requests)))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      for (const name of await caches.keys()) {
        if (name.startsWith(CACHE_PREFIX) && name !== CACHE) await caches.delete(name)
      }
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting()
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET' || request.headers.has('range')) return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  // 서버 API(대화·첨부·오디오)와 앱 도구 경로는 저장하지 않는다. 항상 서버로 간다
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/internal/')) return
  if (request.mode === 'navigate') {
    // 어느 화면 경로로 들어와도 이 버전의 앱 껍데기를 준다(버전이 섞이지 않게 저장본 우선)
    event.respondWith(caches.match(SHELL, MATCH).then((hit) => hit || fetch(request)))
    return
  }
  event.respondWith(cacheFirst(request))
})

async function cacheFirst(request) {
  const cache = await caches.open(CACHE)
  const hit = await cache.match(request, MATCH)
  if (hit) return hit
  const response = await fetch(request)
  // 큰 음성 모델(/vad/)처럼 미리 저장하지 않은 같은 출처 파일은 처음 쓸 때 저장한다
  if (response.ok && response.type === 'basic') await cache.put(request, response.clone())
  return response
}
