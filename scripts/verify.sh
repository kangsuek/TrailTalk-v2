#!/usr/bin/env bash
# 품질 게이트. 모든 검증을 돌리고 실패하면 종료 코드 1로 멈춘다.
#   scripts/verify.sh           전체(빌드·E2E 포함)
#   scripts/verify.sh --quick   타입·린트·단위 테스트까지
# 없는 폴더나 npm 스크립트는 "건너뜀"으로 표시한다.
#
# 속도:
#  - 통과 기록: 문서(docs/, CLAUDE.md, README.md)를 뺀 작업 트리의 git tree 해시가 같으면
#    이미 통과한 단계(quick, full)를 건너뛴다. 기록은 .git/verify-cache/에 둔다.
#    commit에서 통과한 코드로 push하면 build·E2E만 돌고, 문서만 바꾼 변경은 기록이 그대로 맞는다.
#  - 병렬: 서버 검사와 웹 검사를 동시에 돌린다(출력은 끝난 뒤 묶어 보인다).
#  - VERIFY_NO_CACHE=1 기록을 쓰지 않고 항상 전부 돌린다. VERIFY_SERIAL=1 순차로 돌린다.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUICK=0
case "${1:-}" in
  "") ;;
  --quick) QUICK=1 ;;
  *) echo "사용법: scripts/verify.sh [--quick]" >&2; exit 2 ;;
esac

# uv 설치 스크립트는 ~/.local/bin(예전 판은 ~/.cargo/bin)에 설치하지만 PATH에 없을 수 있다
# (훅·에디터가 띄운 셸). run.sh와 같은 방식으로 찾는다
for dir in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
  if [ -x "$dir/uv" ] && ! command -v uv >/dev/null; then
    PATH="$dir:$PATH"
  fi
done

step() { # step <이름> <폴더> <명령...>
  local name="$1" dir="$2"
  shift 2
  echo "▶ $name"
  if (cd "$ROOT/$dir" && "$@"); then
    echo "✔ $name"
  else
    echo "✘ 실패: $name  (명령: $* , 위치: $dir)" >&2
    exit 1
  fi
}

skip() { echo "- 건너뜀: $1 ($2)"; }

has_npm_script() { # has_npm_script <스크립트 이름>
  [ -f "$ROOT/web/package.json" ] &&
    python3 -c 'import json,sys; sys.exit(0 if sys.argv[1] in json.load(open(sys.argv[2])).get("scripts",{}) else 1)' \
      "$1" "$ROOT/web/package.json"
}

web_step() { # web_step <npm 스크립트> [추가 인자...]
  local script="$1"
  shift
  if has_npm_script "$script"; then
    step "web: npm run $script $*" web npm run "$script" ${1:+-- "$@"}
  elif [ -f "$ROOT/web/package.json" ]; then
    skip "web: $script" "web/package.json에 스크립트 없음"
  else
    skip "web: $script" "web/package.json 없음"
  fi
}

# 통과 기록 키: 문서를 뺀 작업 트리의 tree 해시. 임시 인덱스를 써서 실제 인덱스는 건드리지 않는다.
# 키에 들어가지 않는 것: .gitignore로 무시된 파일(.env, .venv, node_modules, server/data), 환경 변수,
# Python·Node 버전. 의심스러우면 VERIFY_NO_CACHE=1로 돌린다. 의존성은 잠금 파일이 추적되므로 반영된다.
# 문서를 읽는 테스트·빌드를 더하면 아래 제외 목록(docs CLAUDE.md README.md)을 함께 고친다.
# 계산에 실패하거나 git이 없으면 빈 문자열을 돌려주고, 기록 없이 전부 돌린다.
compute_key() {
  local tmp key
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/verify-idx.XXXXXX")" || return 0
  key="$(
    {
      cd "$ROOT" &&
        export GIT_INDEX_FILE="$tmp/index" &&
        git read-tree HEAD &&
        git add -A &&
        git rm -r -q --cached --ignore-unmatch -- docs CLAUDE.md README.md &&
        git write-tree
    } 2>/dev/null
  )" || key=""
  rm -rf "$tmp"
  printf '%s' "$key"
}

CACHE_DIR=""
KEY=""
init_cache() {
  [ "${VERIFY_NO_CACHE:-0}" = 1 ] && return 0
  command -v git >/dev/null || return 0
  local dir
  dir="$(git -C "$ROOT" rev-parse --git-path verify-cache 2>/dev/null)" || return 0
  case "$dir" in /*) ;; *) dir="$ROOT/$dir" ;; esac
  KEY="$(compute_key)"
  if [ -n "$KEY" ] && mkdir -p "$dir" 2>/dev/null; then
    CACHE_DIR="$dir"
    find "$CACHE_DIR" -type f -mtime +14 -delete 2>/dev/null || true
  fi
  return 0
}

has_stamp() { [ -n "$CACHE_DIR" ] && [ -f "$CACHE_DIR/$1-$KEY" ]; }
# 검증이 도는 동안 코드가 바뀌었으면(키가 달라졌으면) 섞인 상태를 본 것이므로 기록하지 않는다.
put_stamp() {
  [ -n "$CACHE_DIR" ] || return 0
  if [ "$(compute_key)" = "$KEY" ]; then
    : >"$CACHE_DIR/$1-$KEY"
  else
    echo "= 캐시: 검증 중 코드가 바뀌어 통과 기록을 남기지 않음"
  fi
  return 0
}

# 함수들을 동시에 돌린다. 하나라도 실패하면 전부 기다린 뒤 종료 코드 1로 끝낸다.
# 출력은 각자 끝난 뒤 묶어서 보인다. 중단(INT·TERM)되면 자식과 임시 로그를 정리한다.
run_parallel() {
  local f log i rc=0
  local -a logs=() pids=()
  if [ "${VERIFY_SERIAL:-0}" = 1 ]; then
    for f in "$@"; do "$f" || exit 1; done
    return 0
  fi
  echo "… 병렬 실행 중(출력은 끝난 뒤 한꺼번에 보입니다)"
  trap 'kill "${pids[@]}" 2>/dev/null; rm -f "${logs[@]}"; exit 130' INT TERM
  for f in "$@"; do
    log="$(mktemp "${TMPDIR:-/tmp}/verify-log.XXXXXX")"
    logs+=("$log")
    ("$f") >"$log" 2>&1 &
    pids+=("$!")
  done
  for i in "${!pids[@]}"; do
    wait "${pids[$i]}" || rc=1
    cat "${logs[$i]}"
    rm -f "${logs[$i]}"
  done
  trap - INT TERM
  [ "$rc" -eq 0 ] || exit 1
}

# pytest 워커 수: 기본 6, CPU가 적으면(CI 러너 등) 그 수 이하. VERIFY_PYTEST_WORKERS로 직접 정한다.
pytest_workers() {
  local cpus workers=6
  if [ -n "${VERIFY_PYTEST_WORKERS:-}" ]; then
    printf '%s' "$VERIFY_PYTEST_WORKERS"
    return 0
  fi
  cpus="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
  [ "$cpus" -lt "$workers" ] && workers="$cpus"
  printf '%s' "$workers"
}

require_web_modules() {
  if [ -f "$ROOT/web/package.json" ] && [ ! -d "$ROOT/web/node_modules" ]; then
    echo "✘ web/node_modules가 없습니다. web/에서 npm ci를 먼저 실행하세요." >&2
    exit 1
  fi
}

server_checks() {
  if [ -f "$ROOT/server/pyproject.toml" ]; then
    step "server: ruff check" server uv run ruff check
    step "server: ruff format --check" server uv run ruff format --check
    # 워커를 CPU 수만큼 늘리면 웹 검사와 겹칠 때 시간에 민감한 테스트(CLI 인터럽트 유예 등)가 흔들린다
    step "server: pytest" server uv run pytest -q -n "$(pytest_workers)"
  else
    skip "server" "server/pyproject.toml 없음"
  fi
}

web_quick_checks() {
  require_web_modules
  web_step typecheck
  web_step typecheck:core
  web_step lint
  web_step test
  web_step gen:api --check
}

web_full_checks() {
  require_web_modules
  web_step build
  web_step e2e
}

init_cache

if has_stamp quick || has_stamp full; then
  echo "= 캐시: 같은 코드 상태에서 정적 검사·단위 테스트를 이미 통과해 건너뜀"
else
  run_parallel server_checks web_quick_checks
  put_stamp quick
fi

if [ "$QUICK" -eq 0 ]; then
  if has_stamp full; then
    echo "= 캐시: 같은 코드 상태에서 빌드·E2E를 이미 통과해 건너뜀"
  else
    web_full_checks
    put_stamp full
  fi
fi

echo "모든 검증 통과$([ "$QUICK" -eq 1 ] && echo ' (--quick)')"
