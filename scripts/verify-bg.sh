#!/usr/bin/env bash
# 커밋 뒤 백그라운드 전체 검증과 push 허가 확인.
#   scripts/verify-bg.sh start [<rev>]   전체 검증을 백그라운드로 시작한다(기본 HEAD). 이미 통과했거나
#                                        돌고 있거나 실패한 커밋이면 건너뛴다. 다른 커밋을 검증 중이면 취소한다.
#   scripts/verify-bg.sh gate  [<rev>]   push 게이트. 통과 기록이 있으면 0, 돌고 있으면 끝날 때까지 기다리고,
#                                        실패했으면 로그 끝을 보이고 1. 시작하지 않았으면 시작해서 기다린다.
#   scripts/verify-bg.sh retry [<rev>]   실패 기록을 지우고 다시 시작한다.
#   scripts/verify-bg.sh status          최근 실행 상태를 보인다.
#   scripts/verify-bg.sh run <sha>       (내부) 격리 워크트리에서 실제 검증을 돌린다.
#
# 검증은 커밋된 SHA를 전용 워크트리(~/.cache/trailtalk-verify/<저장소>)에 풀어서 돌리므로, 그 뒤에 작업 트리를 고쳐도 결과가
# 섞이지 않는다. 낮은 우선순위(nice)로 돌고, E2E는 개발 쪽과 겹치지 않는 다른 포트(8110·5184·8411)를 쓴다.
# 통과하면 scripts/verify.sh가 공용 .git/verify-cache/에 남기는 기록이 push 허가증이다.
# 끝나면 맥 알림으로 결과를 알린다. 로그와 상태는 .git/verify-bg/<sha>.log·.status.
set -u
# git 훅(post-commit·pre-push 등)에서 불리면 GIT_DIR·GIT_INDEX_FILE(상대 경로) 같은 값이 넘어와, 격리 워크트리의
# git 명령이 엉뚱한 저장소·인덱스를 건드릴 수 있다. 이 스크립트는 경로를 -C로 직접 정하므로 모두 지운다
unset GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE GIT_PREFIX GIT_COMMON_DIR GIT_OBJECT_DIRECTORY \
  GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_QUARANTINE_PATH GIT_EXEC_PATH

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
ROOT="$(cd "$(dirname "$SELF")/.." && pwd)"
COMMON="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)"
BG="$COMMON/verify-bg"
mkdir -p "$BG"
# 검증용 워크트리는 .git 밖에 둔다(Vite가 경로에 .git이 있는 파일의 제공을 막아 시험이 깨진다)
WT="${VERIFY_BG_WORKTREE:-${XDG_CACHE_HOME:-$HOME/.cache}/trailtalk-verify/$(basename "$(dirname "$COMMON")")}"

resolve() { git -C "$ROOT" rev-parse --verify -q "$1^{commit}"; }
key_of() { VERIFY_REV="$1" "$ROOT/scripts/verify.sh" --key; }
has_full() { [ -n "$2" ] && [ -f "$COMMON/verify-cache/full-$2" ]; }
read_status() { cat "$BG/$1.status" 2>/dev/null || echo none; }
runner_pid() { cat "$BG/run.pid" 2>/dev/null; }
runner_sha() { cat "$BG/run.sha" 2>/dev/null; }
# 실행기가 살아 있는지. PID만 보면 재부팅·오래된 run.pid 뒤에 같은 PID를 쓰는 남의 프로세스를 실행기로 착각해
# 그 프로세스 그룹을 죽일 수 있으므로, 명령줄이 이 스크립트의 run인지도 확인한다
runner_alive() {
  local pid
  pid="$(runner_pid)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null &&
    ps -o command= -p "$pid" 2>/dev/null | grep -q "verify-bg.sh run"
}

# start가 겹쳐 run.pid·run.sha를 서로 덮어쓰지 않게 직렬화한다(mkdir은 원자적). 1분 넘은 잠금은 낡은 것으로 본다
lock_start() {
  local i
  for i in $(seq 1 100); do
    mkdir "$BG/start.lock" 2>/dev/null && return 0
    find "$BG/start.lock" -maxdepth 0 -mmin +1 -exec rmdir {} \; 2>/dev/null
    sleep 0.1
  done
  return 1
}
unlock_start() { rmdir "$BG/start.lock" 2>/dev/null || true; }

# running으로 적혀 있어도 실행기가 죽었거나 다른 커밋을 돌고 있으면 dead
eff_status() {
  local s
  s="$(read_status "$1")"
  if [ "$s" = running ] && { ! runner_alive || [ "$(runner_sha)" != "$1" ]; }; then
    echo dead
  else
    echo "$s"
  fi
}

notify() { # notify <제목> <내용>
  command -v osascript >/dev/null || return 0
  local title="${1//[\"\\]/}" body="${2//[\"\\]/}"
  osascript -e "display notification \"$body\" with title \"$title\"" >/dev/null 2>&1 || true
}

cancel_running() {
  runner_alive || return 0
  local pid sha i
  pid="$(runner_pid)"
  sha="$(runner_sha)"
  kill -TERM -- "-$pid" 2>/dev/null
  for i in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
  done
  kill -KILL -- "-$pid" 2>/dev/null
  [ -n "$sha" ] && echo cancelled >"$BG/$sha.status"
  return 0
}

cmd_start() {
  local sha key rc
  sha="$(resolve "${1:-HEAD}")" || { echo "커밋을 찾을 수 없습니다: ${1:-HEAD}" >&2; return 1; }
  key="$(key_of "$sha")"
  if has_full "$sha" "$key"; then
    echo "= 이미 통과한 코드입니다(${sha:0:7})"
    return 0
  fi
  lock_start || { echo "다른 검증 시작이 끝나길 기다렸지만 잠금을 얻지 못했습니다(${sha:0:7})." >&2; return 1; }
  trap 'unlock_start; exit 143' INT TERM HUP # 잠금을 쥔 채 죽어 잠금이 남지 않게 한다
  start_locked "$sha"
  rc=$?
  trap - INT TERM HUP
  unlock_start
  return "$rc"
}

# 잠금 안에서: 상태를 확인하고 실행기를 띄운다
start_locked() {
  local sha="$1"
  case "$(eff_status "$sha")" in
    running | fail) return 0 ;;
  esac
  find "$BG" -type f \( -name '*.log' -o -name '*.status' \) -mtime +7 -delete 2>/dev/null || true
  cancel_running
  echo running >"$BG/$sha.status"
  : >"$BG/$sha.log"
  echo "$sha" >"$BG/run.sha"
  # 새 세션(setsid)으로 띄워 훅·셸이 끝나도 계속 돌고, 취소할 때 프로세스 그룹째 끈다
  perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV' -- nice -n 10 "$SELF" run "$sha" >>"$BG/$sha.log" 2>&1 </dev/null &
  echo $! >"$BG/run.pid"
  disown 2>/dev/null || true
  echo "… 백그라운드 전체 검증 시작: ${sha:0:7} (끝나면 알림. 로그: $BG/$sha.log)"
}

cmd_run() {
  local sha="$1" wt="$WT" rc subject
  trap 'echo cancelled >"$BG/$sha.status"; exit 143' TERM INT
  subject="$(git -C "$ROOT" log -1 --format=%s "$sha" 2>/dev/null)"

  mkdir -p "$COMMON/info"
  grep -qx '/web/node_modules' "$COMMON/info/exclude" 2>/dev/null || echo '/web/node_modules' >>"$COMMON/info/exclude"

  git -C "$ROOT" worktree prune
  if [ -e "$wt/.git" ]; then
    git -C "$wt" checkout -q --detach -f "$sha" && git -C "$wt" clean -fdq
  else
    mkdir -p "$(dirname "$wt")" && git -C "$ROOT" worktree add -q --detach -f "$wt" "$sha"
  fi || { echo "워크트리 준비 실패"; echo fail >"$BG/$sha.status"; notify "TrailTalk 검증 실패" "${sha:0:7} 워크트리 준비 실패"; exit 1; }

  # 의존성 잠금이 같으면 메인의 node_modules를 연결하고, 다르면 그 커밋 기준으로 설치한다
  if cmp -s "$ROOT/web/package-lock.json" "$wt/web/package-lock.json"; then
    if [ ! -L "$wt/web/node_modules" ]; then
      rm -rf "$wt/web/node_modules"
      ln -s "$ROOT/web/node_modules" "$wt/web/node_modules"
    fi
  else
    [ -L "$wt/web/node_modules" ] && rm "$wt/web/node_modules"
    (cd "$wt/web" && npm ci --silent) || { echo "npm ci 실패"; echo fail >"$BG/$sha.status"; notify "TrailTalk 검증 실패" "${sha:0:7} npm ci 실패"; exit 1; }
  fi

  export VERIFY_PYTEST_WORKERS="${VERIFY_PYTEST_WORKERS:-4}"
  export E2E_API_PORT="${E2E_API_PORT:-8110}" E2E_WEB_PORT="${E2E_WEB_PORT:-5184}" E2E_MCP_PORT="${E2E_MCP_PORT:-8411}"
  echo "▶ 격리 워크트리에서 전체 검증: ${sha:0:7} $subject"
  (cd "$wt" && ./scripts/verify.sh)
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo pass >"$BG/$sha.status"
    notify "TrailTalk 검증 통과 ✔" "${sha:0:7} $subject — push해도 됩니다"
  else
    echo fail >"$BG/$sha.status"
    notify "TrailTalk 검증 실패 ✘" "${sha:0:7} $subject — 로그: .git/verify-bg/${sha:0:7}…log"
  fi
  exit "$rc"
}

cmd_gate() {
  local sha key st tries=0 waited=0 timeout="${VERIFY_GATE_TIMEOUT:-1200}"
  sha="$(resolve "${1:-HEAD}")" || { echo "커밋을 찾을 수 없습니다: ${1:-HEAD}" >&2; return 1; }
  key="$(key_of "$sha")"
  if [ -z "$key" ]; then
    # 작업 트리를 대신 검증하면 올라가는 커밋과 다른 것을 확인하게 되므로 막는다
    echo "✘ 통과 기록 키를 계산하지 못해 ${sha:0:7}의 검증 여부를 확인할 수 없습니다(git 상태를 확인하세요)." >&2
    return 1
  fi
  while :; do
    if has_full "$sha" "$key"; then
      echo "= 통과 기록 확인(${sha:0:7}): 전체 검증을 이미 통과했습니다"
      return 0
    fi
    st="$(eff_status "$sha")"
    case "$st" in
      pass) return 0 ;;
      running) ;;
      fail)
        echo "✘ 전체 검증이 실패했습니다(${sha:0:7}). 로그 끝 40줄:" >&2
        tail -n 40 "$BG/$sha.log" >&2
        echo "전체 로그: $BG/$sha.log  (고친 뒤 새로 커밋하거나 scripts/verify-bg.sh retry)" >&2
        return 1
        ;;
      *)
        tries=$((tries + 1))
        if [ "$tries" -gt 3 ]; then
          echo "✘ 백그라운드 검증을 시작하지 못했습니다(${sha:0:7})." >&2
          return 1
        fi
        cmd_start "$sha" >&2
        ;;
    esac
    if [ "$waited" -ge "$timeout" ]; then
      echo "✘ 전체 검증이 ${timeout}초 안에 끝나지 않았습니다(${sha:0:7})." >&2
      return 1
    fi
    [ "$waited" -eq 0 ] && echo "… 전체 검증이 진행 중입니다(${sha:0:7}). 끝날 때까지 기다립니다" >&2
    sleep 2
    waited=$((waited + 2))
  done
}

cmd_retry() {
  local sha
  sha="$(resolve "${1:-HEAD}")" || return 1
  rm -f "$BG/$sha.status"
  cmd_start "$sha"
}

cmd_status() {
  local f sha
  # shellcheck disable=SC2012
  for f in $(ls -t "$BG"/*.status 2>/dev/null | head -5); do
    sha="$(basename "$f" .status)"
    printf '%s  %s  %s\n' "${sha:0:7}" "$(eff_status "$sha")" "$(git -C "$ROOT" log -1 --format=%s "$sha" 2>/dev/null)"
  done
  [ -n "${sha:-}" ] || echo "백그라운드 검증 기록이 없습니다."
}

case "${1:-}" in
  start) cmd_start "${2:-HEAD}" ;;
  gate) cmd_gate "${2:-HEAD}" ;;
  retry) cmd_retry "${2:-HEAD}" ;;
  status) cmd_status ;;
  run) cmd_run "${2:?sha}" ;;
  *) echo "사용법: scripts/verify-bg.sh start|gate|retry|status [<rev>]" >&2; exit 2 ;;
esac
