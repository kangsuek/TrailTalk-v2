#!/usr/bin/env bash
# TrailTalk 앱 실행: 서버(FastAPI, 8000)와 웹(Vite, 5173)을 함께 띄우고 브라우저를 연다.
#
#   ./run.sh            실행(DB는 server/data/trailtalk.db)
#   ./run.sh --tmp      임시 데이터(.run/tmp)로 실행. 실제 DB·첨부를 건드리지 않는 확인용
#   ./run.sh --no-open  브라우저를 열지 않는다
#   ./run.sh --fake     음성 인식·합성을 과금 없는 가짜로 바꾼다(키 없이 음성 화면 확인용)
#   ./run.sh --mcp      Claude 앱 연계 외부 MCP 서버(포트 MCP_PORT, 기본 8400)를 띄운다. .env나 환경
#                       변수에 MCP_PUBLIC_URL(공개 https 주소)과 MCP_OWNER_PASSWORD(16자 이상)가 있으면
#                       옵션 없이도 자동으로 함께 뜬다(--tmp 제외). 자동일 때 포트가 사용 중이면 MCP만 건너뛰고,
#                       --mcp로 명시했는데 설정이 없거나 포트가 사용 중이면 안내하고 멈춘다.
#   ./run.sh --no-mcp   설정이 있어도 외부 MCP 서버를 띄우지 않는다
#   ./run.sh --mcp-revoke-all  발급된 MCP 토큰을 모두 폐기한다
#   ./run.sh --phone    폰에서 접속한다. 폰은 HTTPS(Tailscale)로 접속해야 하므로 이 기기의 Tailscale 주소를 개발
#                       서버 호스트 허용과 서버의 Origin 허용 목록(ALLOWED_ORIGINS)에 더하고, tailnet 안에서만
#                       여는 HTTPS 주소(기본 포트 8443, PHONE_HTTPS_PORT로 변경)와 켜는 명령을 안내한다.
#                       Tailscale 설정은 바꾸지 않는다(이미 쓰는 serve·Funnel을 건드리지 않음)
#   ./run.sh --build    웹을 운영 빌드한다. 서버(API_PORT)가 그 빌드를 함께 서빙해 서비스 워커(PWA: 오프라인
#                       앱 껍데기·새 버전 적용)를 http://127.0.0.1:<API_PORT>에서 쓸 수 있다. 개발 서버(WEB_PORT,
#                       HMR)는 서비스 워커를 등록하지 않는다
#
# 포트는 API_PORT·WEB_PORT 환경 변수로 바꿀 수 있다(예: API_PORT=8100 WEB_PORT=5174 ./run.sh --tmp).
# 변경성 요청(POST·PUT·PATCH·DELETE)은 Origin이 허용 목록에 있어야 한다(CSRF 방어, 계약 1.5). 기본은 이 실행의
# 서버·웹 주소(127.0.0.1·localhost)이고, 직접 지정한 ALLOWED_ORIGINS(쉼표 구분)에는 폰 주소만 더한다.
# Ctrl+C로 둘 다 종료한다. 다른 터미널에서 끄려면 ./stop.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
RUN_DIR="$ROOT/.run"
PID_FILE="$RUN_DIR/run.pid"
MCP_PID_FILE="$RUN_DIR/mcp.pid" # 떠 있는 외부 MCP 서버만 따로 끌 때(./stop.sh --mcp) 쓴다
TMP=0
OPEN=1
FAKE=0
MCP=0
MCP_AUTO=0
NO_MCP=0
MCP_REVOKE=0
PHONE=0
BUILD=0
MCP_PORT_ENV="${MCP_PORT:-}"

for arg in "$@"; do
  case "$arg" in
    --tmp) TMP=1 ;;
    --no-open) OPEN=0 ;;
    --fake) FAKE=1 ;;
    --mcp) MCP=1 ;;
    --no-mcp) NO_MCP=1 ;;
    --mcp-revoke-all) MCP_REVOKE=1 ;;
    --phone) PHONE=1 ;;
    --build) BUILD=1 ;;
    -h | --help)
      awk 'NR > 1 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "$0" # 머리말 주석 전체
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

# 폰 접속(--phone): 폰의 마이크는 HTTPS 페이지에서만 열리므로 Tailscale HTTPS 주소가 필요하다.
# 여기서는 이 기기의 tailnet 주소를 알아내 개발 서버가 그 호스트를 받게 하고, 켜는 명령을 안내한다.
# tailscale serve 설정은 바꾸지 않는다(이 기기는 443을 Funnel로 외부 MCP에 쓸 수 있다). Funnel은 쓰지 않는다
PHONE_URL=""
PHONE_HTTPS_PORT="${PHONE_HTTPS_PORT:-8443}"
if [ "$PHONE" = 1 ]; then
  TS_BIN="${TAILSCALE_BIN:-}"
  if [ -z "$TS_BIN" ]; then
    for cand in tailscale /Applications/Tailscale.app/Contents/MacOS/Tailscale; do
      if command -v "$cand" >/dev/null 2>&1; then TS_BIN="$(command -v "$cand")"; break; fi
    done
  fi
  if [ -z "$TS_BIN" ] || [ ! -x "$TS_BIN" ]; then
    echo "Tailscale을 찾지 못했습니다. 폰 접속(--phone)에는 Tailscale이 필요합니다." >&2
    echo "  이 기기와 폰에 Tailscale을 설치하고 같은 계정으로 로그인한 뒤 다시 실행하세요: https://tailscale.com/download" >&2
    exit 1
  fi
  PHONE_HOST="$("$TS_BIN" status --json 2>/dev/null | node -e 'let s="";process.stdin.on("data",c=>s+=c).on("end",()=>{try{console.log((JSON.parse(s).Self.DNSName||"").replace(/\.$/,""))}catch(e){}})' || true)"
  if [ -z "$PHONE_HOST" ]; then
    echo "Tailscale 주소를 알아내지 못했습니다. Tailscale에 로그인되어 있는지, MagicDNS·HTTPS 인증서가" >&2
    echo "  켜져 있는지 확인하세요(관리 콘솔 DNS 설정: https://login.tailscale.com/admin/dns)." >&2
    exit 1
  fi
  PHONE_URL="https://$PHONE_HOST:$PHONE_HTTPS_PORT"
  export VITE_ALLOWED_HOSTS="${VITE_ALLOWED_HOSTS:+$VITE_ALLOWED_HOSTS,}$PHONE_HOST" # 미리 지정한 값에 덧붙인다
  echo "폰 접속 모드: 개발 서버가 $PHONE_HOST 를 받도록 합니다."
fi
# CSRF 방어(계약 1.5)의 Origin 허용 목록: 이 실행의 웹·API 주소와, --phone이면 폰 접속 주소.
# ALLOWED_ORIGINS를 직접 지정했으면 그 목록에 폰 주소만 더한다
if [ -n "${ALLOWED_ORIGINS:-}" ]; then
  ORIGINS="$ALLOWED_ORIGINS"
else
  ORIGINS="http://127.0.0.1:$API_PORT,http://localhost:$API_PORT,http://127.0.0.1:$WEB_PORT,http://localhost:$WEB_PORT"
fi
if [ -n "$PHONE_URL" ]; then ORIGINS="$ORIGINS,$PHONE_URL"; fi
phone_guide() {
  echo
  echo "폰에서 열려면(폰에도 Tailscale을 켜고 같은 계정으로 로그인):"
  echo "  1) 다른 터미널에서 한 번 실행 — tailnet 안에서만 여는 HTTPS 연결입니다(Funnel이 아님)"
  echo "       $TS_BIN serve --bg --https=$PHONE_HTTPS_PORT http://127.0.0.1:$WEB_PORT"
  echo "  2) 폰 브라우저에서 $PHONE_URL 을 연다(첨부·대화. 음성은 보류라 마이크는 아직 쓰지 않는다)"
  echo "  끄려면: $TS_BIN serve --https=$PHONE_HTTPS_PORT off  (./run.sh를 꺼도 이 연결은 남는다)"
  echo "  이미 $PHONE_HTTPS_PORT 번을 쓰고 있으면 PHONE_HTTPS_PORT=10000 ./run.sh --phone (443은 외부 MCP Funnel이 쓸 수 있어 피한다)"
  echo "  접속이 안 되면: 포트 없는 주소(443)는 외부 MCP용이라 앱이 열리지 않는다(반드시 포트를 붙인다). ./run.sh가"
  echo "    켜져 있어야 하고, 폰의 비공개 DNS·크롬 보안 DNS가 Tailscale 이름 풀이를 막는지도 본다(README의 폰 접속 문제 해결)"
  echo "  서비스 워커(오프라인·새 버전 안내)를 폰에서 쓰려면 ./run.sh --build --phone 으로 띄우고 위 1)의 연결 대상 포트를"
  echo "    서버 포트($API_PORT)로 바꾼다: $TS_BIN serve --bg --https=$PHONE_HTTPS_PORT http://127.0.0.1:$API_PORT"
  echo "ALLOWED_ORIGINS=$ORIGINS"
}
if [ "$PHONE" = 1 ] && [ "${TRAILTALK_TEST_PHONE_GUIDE_ONLY:-0}" = 1 ]; then # 시험용: 안내만 내고 끝낸다
  phone_guide
  exit 0
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
      \"*\"*) value="${value#\"}"; value="${value%%\"*}" ;;
      \'*\'*) value="${value#\'}"; value="${value%%\'*}" ;;
      *) value="${value%%[[:space:]]#*}"; value="${value%"${value##*[![:space:]]}"}" ;;
    esac
  fi
  printf '%s' "$value"
}
MCP_PORT="${MCP_PORT_ENV:-$(mcp_setting MCP_PORT)}"
MCP_PORT="${MCP_PORT:-8400}"
if [ "$MCP" = 1 ] && [ "$NO_MCP" = 1 ]; then
  echo "--mcp와 --no-mcp는 함께 쓸 수 없습니다." >&2
  exit 2
fi
# 옵션이 없으면 설정이 갖춰졌을 때만 자동으로 켠다. 임시 모드(--tmp)에서는 자동으로 켜지 않는다
if [ "$MCP" = 0 ] && [ "$NO_MCP" = 0 ] && [ "$MCP_REVOKE" = 0 ] && [ "$TMP" = 0 ]; then
  auto_url="$(mcp_setting MCP_PUBLIC_URL)"
  auto_password="$(mcp_setting MCP_OWNER_PASSWORD)"
  if [ -n "$auto_url" ] && [ "${#auto_password}" -ge 16 ]; then
    MCP=1
    MCP_AUTO=1
    echo "외부 MCP 서버를 자동으로 함께 띄웁니다(공개 주소 $auto_url). 끄려면 --no-mcp"
  else
    echo "외부 MCP 서버는 띄우지 않습니다(.env에 MCP_PUBLIC_URL·MCP_OWNER_PASSWORD가 없음)."
  fi
fi
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
if [ "$MCP_AUTO" = 1 ] && port_in_use "$MCP_PORT"; then
  echo "포트 $MCP_PORT 이(가) 사용 중이라 외부 MCP 서버는 건너뜁니다(--no-mcp로 이 안내를 끌 수 있음)." >&2
  MCP=0
  ports=("$API_PORT" "$WEB_PORT")
fi
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

if [ "$BUILD" = 1 ]; then
  # 서버(API_PORT)는 web/dist가 있으면 그 빌드를 함께 서빙한다. 서비스 워커(PWA)는 이 빌드에서만 등록된다
  echo "웹을 운영 빌드합니다(web/dist)…"
  (cd "$ROOT/web" && npm run build >/dev/null)
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

export ALLOWED_ORIGINS="$ORIGINS" # 위에서 정한 CSRF 허용 Origin을 서버에 넘긴다

mkdir -p "$RUN_DIR"
# PID 파일: 1행 PID, 2행 시작 시각(stop.sh가 PID 재사용을 가려내는 데 쓴다)
{ echo "$$"; ps -p "$$" -o lstart=; } >"$PID_FILE"
# 폰 접속(--phone)으로 연 Tailscale 연결은 run.sh를 꺼도 남으므로, ./stop.sh가 끄는 방법을 알리도록 적어 둔다
if [ "$PHONE" = 1 ]; then
  echo "$TS_BIN serve --https=$PHONE_HTTPS_PORT off" >"$RUN_DIR/phone"
else
  rm -f "$RUN_DIR/phone"
fi

PIDS=()
MCP_PID="" # 자동으로 띄운 MCP 서버. 실패해도 서버·웹은 계속 띄우므로 PIDS 밖에서 따로 관리한다
# bash 3.2(macOS)는 set -u에서 빈 배열을 "${PIDS[@]}"로 펼치면 오류가 나므로 ${PIDS[@]+...}로 쓴다
stop_all() {
  for pid in ${PIDS[@]+"${PIDS[@]}"} ${MCP_PID:+"$MCP_PID"}; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -f "$PID_FILE" "$MCP_PID_FILE"
  if [ "$PHONE" = 1 ]; then # tailscale serve는 우리가 띄운 프로세스가 아니라 run.sh를 꺼도 남는다
    echo "폰 접속용 Tailscale 연결(포트 $PHONE_HTTPS_PORT)은 그대로 남아 있습니다. 끄려면: $TS_BIN serve --https=$PHONE_HTTPS_PORT off"
  fi
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
  mcp_pid=$!
  mcp_check="http://127.0.0.1:$MCP_PORT/.well-known/oauth-authorization-server"
  if [ "$MCP_AUTO" = 1 ]; then
    # 자동으로 띄운 MCP 서버가 실패해도 서버와 웹은 그대로 쓸 수 있게 MCP만 건너뛴다
    MCP_PID=$mcp_pid
    mcp_ok=0
    for _ in $(seq 1 120); do
      if curl -sf "$mcp_check" >/dev/null 2>&1; then mcp_ok=1; break; fi
      kill -0 "$mcp_pid" 2>/dev/null || break
      sleep 0.5
    done
    if [ "$mcp_ok" = 1 ]; then
      echo "외부 MCP 서버: http://127.0.0.1:$MCP_PORT/mcp (공개 주소 $(mcp_setting MCP_PUBLIC_URL)/mcp)"
    else
      echo "외부 MCP 서버를 시작하지 못해 건너뜁니다(서버·웹은 계속 실행). 원인은 위 로그를 보세요." >&2
      kill "$mcp_pid" 2>/dev/null || true
      MCP_PID=""
    fi
  else
    PIDS+=("$mcp_pid")
    wait_for "$mcp_check" "외부 MCP 서버"
    # 시작을 확인한 뒤에는 감시 목록에서 뺀다: 외부 MCP 서버만 따로 꺼도(./stop.sh --mcp) 서버와 웹은 계속 돈다
    unset 'PIDS[${#PIDS[@]}-1]'
    MCP_PID=$mcp_pid
    echo "외부 MCP 서버: http://127.0.0.1:$MCP_PORT/mcp (공개 주소 $(mcp_setting MCP_PUBLIC_URL)/mcp)"
  fi
  # 떠 있는 외부 MCP 서버만 ./stop.sh --mcp로 끌 수 있게 PID와 시작 시각을 남긴다(자동·명시 실행 모두)
  if [ -n "$MCP_PID" ]; then
    { echo "$MCP_PID"; ps -p "$MCP_PID" -o lstart= || true; } >"$MCP_PID_FILE" # 그사이 죽었으면 시작 시각이 비어 stop.sh가 낡은 기록으로 본다
  fi
fi
URL="http://127.0.0.1:$WEB_PORT"
echo
echo "TrailTalk 실행 중: $URL  (서버 http://127.0.0.1:$API_PORT, 종료: Ctrl+C 또는 ./stop.sh)"
echo "허용 Origin(변경성 요청, CSRF 방어): $ORIGINS"
if [ "$BUILD" = 1 ]; then
  echo "운영 빌드: http://127.0.0.1:$API_PORT 에서 서비스 워커(PWA)가 동작합니다(개발 서버 $URL 은 등록하지 않음)"
fi
[ "$PHONE" = 1 ] && phone_guide
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
  if [ -n "$MCP_PID" ] && ! kill -0 "$MCP_PID" 2>/dev/null; then
    echo "외부 MCP 서버가 종료되었습니다(서버·웹은 계속 실행). 다시 띄우려면 ./stop.sh 후 ./run.sh" >&2
    MCP_PID=""
    rm -f "$MCP_PID_FILE"
  fi
  sleep 1
done
