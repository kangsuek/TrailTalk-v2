#!/usr/bin/env bash
# run.sh로 띄운 서버와 웹을 끈다. 이 저장소의 run.sh(PID 파일 .run/run.pid)만 종료하고,
# 다른 프로그램이나 다른 곳에서 띄운 서버(예: 포트 8000의 다른 서버)는 건드리지 않는다.
# 사용법: ./stop.sh          run.sh로 띄운 서버·웹과 외부 MCP 서버(자동 또는 --mcp로 띄운 것)를 모두 끈다
#         ./stop.sh --mcp    외부 MCP 서버(Claude 앱 연계)만 끈다. 서버와 웹은 계속 돈다
# ./run.sh --phone으로 연 Tailscale 연결(tailscale serve)은 run.sh를 꺼도 남는다. 이 스크립트는 그것을 끄지
# 않고(Tailscale 설정은 바꾸지 않는다), 끄는 명령을 한 번 알려 준다(.run/phone에 run.sh가 적어 둔다).
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$ROOT/.run/run.pid"
MCP_PID_FILE="$ROOT/.run/mcp.pid"
PHONE_FILE="$ROOT/.run/phone" # run.sh --phone이 적어 둔 "연결을 끄는 명령"

# 외부 MCP 서버를 끈다. 돌려주는 값: 0 끔, 1 PID 파일이 없음, 2 이미 끝났음(낡은 PID 파일을 지움).
# PID가 재사용됐을 수 있으므로 같은 프로세스인지 시작 시각(PID 파일 2행)으로 확인한다
stop_mcp() {
  [ -f "$MCP_PID_FILE" ] || return 1
  local pid started
  pid="$(head -n 1 "$MCP_PID_FILE")"
  started="$(sed -n 2p "$MCP_PID_FILE")"
  if ! [[ "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null ||
    [ "$(ps -p "$pid" -o lstart= 2>/dev/null)" != "$started" ]; then
    rm -f "$MCP_PID_FILE"
    return 2
  fi
  pkill -TERM -P "$pid" 2>/dev/null || true # uv가 띄운 파이썬 자식까지 끈다
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || { rm -f "$MCP_PID_FILE"; return 0; }
    sleep 0.5
  done
  echo "외부 MCP 서버가 10초 안에 끝나지 않아 강제로 종료합니다." >&2
  pkill -KILL -P "$pid" 2>/dev/null || true
  kill -KILL "$pid" 2>/dev/null || true
  rm -f "$MCP_PID_FILE"
  return 0
}

case "${1:-}" in
  "") ;;
  --mcp)
    stop_mcp
    case $? in
      0) echo "외부 MCP 서버를 종료했습니다(서버와 웹은 계속 실행 중)." ;;
      1) echo "run.sh로 띄운 외부 MCP 서버가 없습니다." ;;
      *) echo "외부 MCP 서버가 이미 끝났습니다. PID 파일을 지웁니다." ;;
    esac
    exit 0
    ;;
  *)
    echo "알 수 없는 옵션: $1 (사용: ./stop.sh [--mcp])" >&2
    exit 2
    ;;
esac

# run.sh가 끝난 뒤 남은 외부 MCP 서버(run.sh가 먼저 죽었거나 강제 종료한 경우)도 끈다
stop_leftover_mcp() {
  stop_mcp
  [ $? -eq 0 ] && echo "남아 있던 외부 MCP 서버도 종료했습니다."
  return 0
}

# 폰 접속용 Tailscale 연결이 남아 있으면(--phone) 끄는 명령을 알린다. 한 번 알리면 기록을 지운다
remind_phone() {
  [ -f "$PHONE_FILE" ] || return 0
  echo "폰 접속용 Tailscale 연결은 그대로 남아 있습니다(앞에서 ./run.sh --phone으로 열었다면). 끄려면: $(head -n 1 "$PHONE_FILE")"
  rm -f "$PHONE_FILE"
}

if [ ! -f "$PID_FILE" ]; then
  echo "실행 중인 run.sh가 없습니다."
  stop_leftover_mcp
  remind_phone
  exit 0
fi
PID="$(head -n 1 "$PID_FILE")"
STARTED="$(sed -n 2p "$PID_FILE")"
# PID가 재사용됐을 수 있으므로 같은 프로세스인지 시작 시각으로 확인한다(PID 파일의 2행)
if ! [[ "$PID" =~ ^[0-9]+$ ]] || ! kill -0 "$PID" 2>/dev/null ||
  [ "$(ps -p "$PID" -o lstart= 2>/dev/null)" != "$STARTED" ]; then
  echo "run.sh(PID $PID)가 이미 끝났습니다. PID 파일을 지웁니다."
  rm -f "$PID_FILE"
  stop_leftover_mcp
  remind_phone
  exit 0
fi

kill -TERM "$PID"  # run.sh의 종료 처리가 서버와 웹, 외부 MCP 서버를 함께 끈다
for _ in $(seq 1 20); do
  kill -0 "$PID" 2>/dev/null || { echo "종료했습니다."; rm -f "$PID_FILE"; stop_leftover_mcp; remind_phone; exit 0; }
  sleep 0.5
done
echo "10초 안에 끝나지 않아 강제로 종료합니다." >&2
pkill -KILL -P "$PID" 2>/dev/null || true  # 서버·웹 자식까지 정리한다
kill -KILL "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
stop_leftover_mcp
remind_phone
