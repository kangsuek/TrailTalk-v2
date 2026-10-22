#!/usr/bin/env bash
# run.sh로 띄운 서버와 웹을 끈다. 이 저장소의 run.sh(PID 파일 .run/run.pid)만 종료하고,
# 다른 프로그램이나 다른 곳에서 띄운 서버(예: 포트 8000의 다른 서버)는 건드리지 않는다.
set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$ROOT/.run/run.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "실행 중인 run.sh가 없습니다."
  exit 0
fi
PID="$(head -n 1 "$PID_FILE")"
STARTED="$(sed -n 2p "$PID_FILE")"
# PID가 재사용됐을 수 있으므로 같은 프로세스인지 시작 시각으로 확인한다(PID 파일의 2행)
if ! [[ "$PID" =~ ^[0-9]+$ ]] || ! kill -0 "$PID" 2>/dev/null ||
  [ "$(ps -p "$PID" -o lstart= 2>/dev/null)" != "$STARTED" ]; then
  echo "run.sh(PID $PID)가 이미 끝났습니다. PID 파일을 지웁니다."
  rm -f "$PID_FILE"
  exit 0
fi

kill -TERM "$PID"  # run.sh의 종료 처리가 서버와 웹을 함께 끈다
for _ in $(seq 1 20); do
  kill -0 "$PID" 2>/dev/null || { echo "종료했습니다."; rm -f "$PID_FILE"; exit 0; }
  sleep 0.5
done
echo "10초 안에 끝나지 않아 강제로 종료합니다." >&2
pkill -KILL -P "$PID" 2>/dev/null || true  # 서버·웹 자식까지 정리한다
kill -KILL "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
