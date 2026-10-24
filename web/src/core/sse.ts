// SSE(text/event-stream) 파서. 턴 요청이 POST라 EventSource 대신 fetch 스트림을 직접 읽는다.
// UI·브라우저 API에 의존하지 않는다. 바이트 디코딩은 호출하는 쪽이 한다.
// 줄 끝은 표준대로 \r\n, \r, \n만 본다. U+2028 같은 문자는 데이터 안에 그대로 둔다.

export interface SseMessage {
  event: string
  data: string
}

export class SseParser {
  private buffer = ''
  private started = false
  private event = ''
  private data: string[] = []

  /** 받은 텍스트 조각을 넣고, 빈 줄로 끝난 메시지들을 돌려준다. */
  feed(chunk: string): SseMessage[] {
    if (!this.started && chunk) {
      // 스트림 맨 앞의 BOM은 버린다(표준). 웹은 TextDecoder가 이미 지우지만 디코더와 상관없이 같게 동작하도록
      this.started = true
      if (chunk.startsWith('\uFEFF')) chunk = chunk.slice(1)
    }
    this.buffer += chunk
    const messages: SseMessage[] = []
    let start = 0
    while (start < this.buffer.length) {
      const lf = this.buffer.indexOf('\n', start)
      const cr = this.buffer.indexOf('\r', start)
      const end = cr === -1 ? lf : lf === -1 ? cr : Math.min(cr, lf)
      if (end === -1) break
      // \r 다음 조각이 \n일 수 있으니 \r로 끝나면 다음 조각을 기다린다
      if (this.buffer[end] === '\r' && end === this.buffer.length - 1) break
      const line = this.buffer.slice(start, end)
      start = end + (this.buffer[end] === '\r' && this.buffer[end + 1] === '\n' ? 2 : 1)
      this.processLine(line, messages)
    }
    this.buffer = this.buffer.slice(start)
    return messages
  }

  /** 스트림 끝. 빈 줄로 끝나지 않은 메시지는 표준대로 버린다. */
  end(): SseMessage[] {
    const messages: SseMessage[] = []
    if (this.buffer.endsWith('\r')) this.processLine(this.buffer.slice(0, -1), messages)
    this.buffer = ''
    this.event = ''
    this.data = []
    return messages
  }

  private processLine(line: string, messages: SseMessage[]): void {
    if (line === '') {
      if (this.data.length > 0) {
        messages.push({ event: this.event || 'message', data: this.data.join('\n') })
      }
      this.event = ''
      this.data = []
      return
    }
    if (line.startsWith(':')) return // 주석(연결 유지용)
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') this.event = value
    else if (field === 'data') this.data.push(value)
  }
}
