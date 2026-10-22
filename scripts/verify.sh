#!/usr/bin/env bash
# 품질 게이트. 모든 검증을 순서대로 돌리고 첫 실패에서 멈춘다.
#   scripts/verify.sh           전체(빌드·E2E 포함)
#   scripts/verify.sh --quick   타입·린트·단위 테스트까지
# 없는 폴더나 npm 스크립트는 "건너뜀"으로 표시한다.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUICK=0
case "${1:-}" in
  "") ;;
  --quick) QUICK=1 ;;
  *) echo "사용법: scripts/verify.sh [--quick]" >&2; exit 2 ;;
esac

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

# 서버
if [ -f "$ROOT/server/pyproject.toml" ]; then
  step "server: ruff check" server uv run ruff check
  step "server: ruff format --check" server uv run ruff format --check
  step "server: pytest" server uv run pytest -q
else
  skip "server" "server/pyproject.toml 없음"
fi

# 웹
if [ -d "$ROOT/web/node_modules" ] || [ ! -f "$ROOT/web/package.json" ]; then
  web_step typecheck
  web_step typecheck:core
  web_step lint
  web_step test
  web_step gen:api --check
  if [ "$QUICK" -eq 0 ]; then
    web_step build
    web_step e2e
  fi
else
  echo "✘ web/node_modules가 없습니다. web/에서 npm ci를 먼저 실행하세요." >&2
  exit 1
fi

echo "모든 검증 통과$([ "$QUICK" -eq 1 ] && echo ' (--quick)')"
