#!/usr/bin/env bash
# TrailTalk 앱 실행: 서버(FastAPI, 8000)와 웹(Vite, 5173)을 함께 띄우고 브라우저를 연다.
#
#   ./run.sh            실행(DB는 server/data/trailtalk.db)
#   ./run.sh --tmp      임시 데이터(.run/tmp)로 실행. 실제 DB·첨부를 건드리지 않는 확인용
#   ./run.sh --no-open  브라우저를 열지 않는다
#   ./run.sh --fake     음성 인식·합성을 과금 없는 가짜로 바꾼다(키 없이 음성 화면 확인용)
#   ./run.sh --mcp      Claude 앱 연계 외부 MCP 서버(포트 MCP_PORT, 기본 8400)도 함께 띄운다.
#                       MCP_PUBLIC_URL(공개 https 주소)과 MCP_OWNER_PASSWORD(16자 이상)가 .env에
#                       없으면 시작하지 않고 안내한다. 토큰 전체 폐기: ./run.sh --mcp-revoke-all
#
# 포트는 API_PORT·WEB_PORT 환경 변수로 바꿀 수 있다(예: API_PORT=8100 WEB_PORT=5174 ./run.sh --tmp).
# Ctrl+C로 둘 다 종료한다. 다른 터미널에서 끄려면 ./stop.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
RUN_DIR="$ROOT/.run"
PID_FILE="$RUN_DIR/run.pid"
TMP=0
OPEN=1
FAKE=0
MCP=0
MCP_REVOKE=0
MCP_PORT_ENV="${MCP_PORT:-}"

for arg in "$@"; do
  case "$arg" in
    --tmp) TMP=1 ;;
    --no-open) OPEN=0 ;;
    --fake) FAKE=1 ;;
    --mcp) MCP=1 ;;
    --mcp-revoke-all) MCP_REVOKE=1 ;;
    -h | --help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "알 수 없는 옵션: $arg (--help 참고)" >&2
      exit 2
      ;;
  esac
done

# uv 설치 스크립트는 ~/.local/bin(예전 판은 ~/.cargo/bin)에 설치하지만 셸 PATH에 넣지 않았을 수 있다
for dir in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
  if [ -x "$dir/uv" ] && ! command -v uv >/dev/null; then
    PATH="$dir:$PATH"
  fi
done

install_hint() { # install_hint <명령>: 없는 도구의 설치 방법
  case "$1" in
    uv)
      echo "  uv(Python 패키지 관리자, Python 3.12는 uv가 받는다):"
      echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
      echo "    설치 뒤 새 터미널을 열거나: source \"\$HOME/.local/bin/env\""
      ;;
    node | npm)
      echo "  Node.js 24(npm 포함):"
      echo "    https://nodejs.org 에서 24 LTS 설치 파일을 받아 설치"
      echo "    또는 Homebrew: brew install node@24 (안내대로 PATH 추가)"
      ;;
    *)
      echo "  $1: macOS 기본 도구입니다. PATH에 /usr/bin·/usr/sbin이 있는지 확인하세요."
      ;;
  esac
}

missing=()
for cmd in uv node npm curl lsof; do
  command -v "$cmd" >/dev/null || missing+=("$cmd")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "필요한 명령이 없습니다: ${missing[*]}" >&2
  for cmd in "${missing[@]}"; do
    [ "$cmd" = npm ] && [[ " ${missing[*]} " == *" node "* ]] && continue # node와 같은 안내
    install_hint "$cmd" >&2
  done
  echo "설치한 뒤 ./run.sh 를 다시 실행하세요." >&2
  exit 1
fi

node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
case "$node_major" in '' | *[!0-9]*) node_major=0 ;; esac # 고장 난 shim의 엉뚱한 출력은 낮은 버전으로 본다
if [ "$node_major" -lt 24 ]; then
  echo "Node.js 24 이상이 필요합니다(현재 $(node -v 2>/dev/null || echo '알 수 없음'))." >&2
  install_hint node >&2
  exit 1
fi

# 이 저장소의 run.sh가 이미 떠 있으면 중복 실행하지 않는다
if [ -f "$PID_FILE" ] && kill -0 "$(head -n 1 "$PID_FILE")" 2>/dev/null; then
  echo "이미 실행 중입니다(PID $(head -n 1 "$PID_FILE")). 먼저 ./stop.sh 로 끄세요." >&2
  exit 1
fi

# 외부 MCP 서버(--mcp)는 공개 주소와 소유자 비밀번호가 있어야 한다. 값은 셸 환경 변수나 저장소 루트의
# .env에서 읽고(값을 출력하지 않는다), 없으면 서버를 띄우기 전에 멈추고 안내한다.
mcp_setting() { # mcp_setting <KEY>: 환경 변수, 없으면 .env의 값(따옴표와 뒤의 # 주석을 뗀다)
  local key=$1 value="${!1:-}"
  if [ -z "$value" ] && [ -f "$ROOT/.env" ]; then
    value="$(grep -E "^${key}=" "$ROOT/.env" | tail -n 1 | cut -d= -f2- | tr -d '\r' || true)"
    case "$value" in
      \"*\") value="${value#\"}"; value="${value%\"}" ;;
      \'*\') value="${value#\'}"; value="${value%\'}" ;;
      *) value="${value%%[[:space:]]#*}"; value="${value%"${value##*[![:space:]]}"}" ;;
    esac
  fi
  printf '%s' "$value"
}
MCP_PORT="${MCP_PORT_ENV:-$(mcp_setting MCP_PORT)}"
MCP_PORT="${MCP_PORT:-8400}"
if [ "$MCP" = 1 ] || [ "$MCP_REVOKE" = 1 ]; then
  if [ "$MCP_REVOKE" = 0 ]; then
    mcp_url="$(mcp_setting MCP_PUBLIC_URL)"
    mcp_password="$(mcp_setting MCP_OWNER_PASSWORD)"
    if [ -z "$mcp_url" ] || [ "${#mcp_password}" -lt 16 ]; then
      echo "외부 MCP 서버를 시작하지 않습니다. .env(또는 환경 변수)에 다음을 설정하세요:" >&2
      echo "  MCP_PUBLIC_URL=https://<기기 이름>.<tailnet>.ts.net   (끝 슬래시·경로 없이)" >&2
      echo "  MCP_OWNER_PASSWORD=<16자 이상 비밀번호>" >&2
      exit 1
    fi
  fi
fi
if [ "$MCP_REVOKE" = 1 ]; then
  if [ "$TMP" = 1 ]; then
    echo "--mcp-revoke-all은 --tmp와 함께 쓸 수 없습니다(실제 DB의 토큰을 지웁니다)." >&2
    exit 2
  fi
  (cd "$ROOT/server" && uv run python -m app.mcp_external revoke-all)
  exit $?
fi

port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
ports=("$API_PORT" "$WEB_PORT")
[ "$MCP" = 1 ] && ports+=("$MCP_PORT")
for port in "${ports[@]}"; do
  if port_in_use "$port"; then
    echo "포트 $port 이(가) 이미 사용 중입니다. 떠 있는 서버를 먼저 끄세요: lsof -nP -iTCP:$port -sTCP:LISTEN" >&2
    exit 1
  fi
done

# 의존성(처음 한 번). 웹은 package-lock.json이 마지막 설치보다 새로우면 다시 설치한다
(cd "$ROOT/server" && uv sync --quiet)
if [ ! -f "$ROOT/web/node_modules/.package-lock.json" ] ||
  [ "$ROOT/web/package-lock.json" -nt "$ROOT/web/node_modules/.package-lock.json" ]; then
  (cd "$ROOT/web" && npm ci)
fi

if [ "$TMP" = 1 ]; then
  TMP_DIR="$RUN_DIR/tmp"
  rm -rf "$TMP_DIR" && mkdir -p "$TMP_DIR"
  export DATABASE_URL="sqlite+aiosqlite:///$TMP_DIR/trailtalk.db"
  export ATTACHMENTS_DIR="$TMP_DIR/attachments"
  export AUDIO_DIR="$TMP_DIR/audio"
  export CLI_WORK_DIR="$TMP_DIR/cli"
  echo "임시 데이터 모드: $TMP_DIR (실제 DB·첨부를 쓰지 않습니다)"
fi
if [ "$FAKE" = 1 ]; then
  export VOICE_BACKEND=fake
  echo "가짜 음성 모드: 음성 인식·합성을 가짜로 바꿨습니다(과금 없음, 인식은 늘 같은 문장)."
fi
export VITE_API_TARGET="http://127.0.0.1:$API_PORT"  # 셸에 남은 다른 값을 쓰지 않게

mkdir -p "$RUN_DIR"
# PID 파일: 1행 PID, 2행 시작 시각(stop.sh가 PID 재사용을 가려내는 데 쓴다)
{ echo "$$"; ps -p "$$" -o lstart=; } >"$PID_FILE"

PIDS=()
# bash 3.2(macOS)는 set -u에서 빈 배열을 "${PIDS[@]}"로 펼치면 오류가 나므로 ${PIDS[@]+...}로 쓴다
stop_all() {
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -f "$PID_FILE"
}
on_exit() {
  trap - INT TERM HUP EXIT
  stop_all
}
on_signal() {
  trap - INT TERM HUP EXIT
  echo
  echo "종료하는 중…"
  stop_all
  exit 130
}
trap on_signal INT TERM HUP
trap on_exit EXIT

(cd "$ROOT/server" && exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" \
  --timeout-graceful-shutdown 5) &
PIDS+=($!)
(cd "$ROOT/web" && exec npm run dev -- --host 127.0.0.1 --port "$WEB_PORT" --strictPort) &
PIDS+=($!)

wait_for() {
  local url=$1 name=$2
  for _ in $(seq 1 120); do
    curl -sf "$url" >/dev/null 2>&1 && return 0
    for pid in "${PIDS[@]}"; do
      kill -0 "$pid" 2>/dev/null || { echo "$name 이(가) 시작하지 못했습니다." >&2; exit 1; }
    done
    sleep 0.5
  done
  echo "$name 이(가) 60초 안에 응답하지 않습니다." >&2
  exit 1
}
wait_for "http://127.0.0.1:$API_PORT/api/health" "서버"
wait_for "http://127.0.0.1:$WEB_PORT" "웹"
if [ "$MCP" = 1 ]; then
  # 기존 서버가 DB 스키마를 맞춘 뒤(위 서버 응답) 외부 앱을 띄운다. 외부 앱은 마이그레이션하지 않는다
  (cd "$ROOT/server" && exec env MCP_PORT="$MCP_PORT" uv run python -m app.mcp_external serve) &
  PIDS+=($!)
  wait_for "http://127.0.0.1:$MCP_PORT/.well-known/oauth-authorization-server" "외부 MCP 서버"
  echo "외부 MCP 서버: http://127.0.0.1:$MCP_PORT/mcp (공개 주소 $(mcp_setting MCP_PUBLIC_URL)/mcp)"
fi
URL="http://127.0.0.1:$WEB_PORT"
echo
echo "TrailTalk 실행 중: $URL  (서버 http://127.0.0.1:$API_PORT, 종료: Ctrl+C 또는 ./stop.sh)"
# 브라우저 열기에 실패해도 서버는 계속 띄워 둔다
if [ "$OPEN" = 1 ] && command -v open >/dev/null; then open "$URL" || true; fi

# 서버나 웹 중 하나가 죽으면 나머지도 끈다(bash 3.2에는 wait -n이 없어 상태를 살핀다)
while :; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "서버 또는 웹이 종료되어 나머지도 끕니다." >&2
      exit 1
    fi
  done
  sleep 1
done
