// 서버 API 공통 요청. 실패는 서버 공통 오류 형식(client-contract 9절) 또는 네트워크 오류로 바꿔 던진다.

/** 서버 공통 오류 형식 또는 네트워크 오류. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

/** JSON이 아닌 본문(음성 업로드). 바이트를 Content-Type과 함께 그대로 보낸다 */
export class RawBody {
  readonly bytes: Uint8Array<ArrayBuffer>
  readonly contentType: string

  constructor(bytes: Uint8Array<ArrayBuffer>, contentType: string) {
    this.bytes = bytes
    this.contentType = contentType
  }
}

const NETWORK_ERROR = '서버에 연결할 수 없어요.'
const GATEWAY_STATUSES = new Set([502, 503, 504])

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

/** 서버 API 요청(본문은 JSON, RawBody면 바이트 그대로). 응답이 실패면 ApiError를 던진다.
 * 변경성 요청(POST·PUT·PATCH·DELETE)에는 규약 1.5의 X-TrailTalk 헤더를 붙인다(서버 검사는 M6). */
export async function request(
  path: string,
  method: Method,
  body?: unknown,
  signal?: AbortSignal,
): Promise<Response> {
  const headers: Record<string, string> = {}
  if (method !== 'GET') headers['X-TrailTalk'] = '1'
  const raw = body instanceof RawBody ? body : null
  if (body !== undefined) headers['Content-Type'] = raw ? raw.contentType : 'application/json'
  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : raw ? raw.bytes : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new ApiError('network_error', NETWORK_ERROR, 0)
  }
  if (!response.ok) throw await errorOf(response)
  return response
}

async function errorOf(response: Response): Promise<ApiError> {
  try {
    const body = await response.json()
    if (body?.error?.code) {
      return new ApiError(body.error.code, body.error.message, response.status)
    }
  } catch {
    // 본문이 JSON이 아니면 상태 코드로만 알린다
  }
  // 개발 프록시·배포 터널은 서버가 꺼져 있으면 JSON 없이 502·503·504를 준다
  if (GATEWAY_STATUSES.has(response.status)) {
    return new ApiError('network_error', NETWORK_ERROR, response.status)
  }
  return new ApiError('http_error', `요청이 실패했어요(${response.status}).`, response.status)
}
