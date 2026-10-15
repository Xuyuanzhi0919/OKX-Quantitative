#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
LOG_DIR="$RUN_DIR/logs"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
TRADEKIT_PORT="${TRADEKIT_PORT:-8010}"

mkdir -p "$LOG_DIR"

usage() {
  cat <<EOF
Usage: scripts/dev.sh <start|stop|restart|status|logs>

Services:
  backend   http://127.0.0.1:${BACKEND_PORT}
  frontend  http://127.0.0.1:${FRONTEND_PORT}
  tradekit  http://127.0.0.1:${TRADEKIT_PORT}

Environment overrides:
  BACKEND_PORT=8000 FRONTEND_PORT=5173 TRADEKIT_PORT=8010 scripts/dev.sh start
EOF
}

pid_file() {
  echo "$RUN_DIR/$1.pid"
}

log_file() {
  echo "$LOG_DIR/$1.log"
}

port_pid() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

is_pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

service_pid() {
  local name="$1"
  local file
  file="$(pid_file "$name")"
  [[ -f "$file" ]] && cat "$file" || true
}

check_backend() {
  [[ -x "$ROOT_DIR/backend/venv/bin/python" ]] || {
    echo "Missing backend venv: $ROOT_DIR/backend/venv"
    echo "Run: cd backend && python3.11 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
  }
}

check_frontend() {
  [[ -d "$ROOT_DIR/frontend/node_modules" ]] || {
    echo "Missing frontend dependencies: $ROOT_DIR/frontend/node_modules"
    echo "Run: cd frontend && npm install"
    exit 1
  }
}

check_tradekit() {
  [[ -x "$ROOT_DIR/tradekit/.venv/bin/python" ]] || {
    echo "Missing TradeKit venv: $ROOT_DIR/tradekit/.venv"
    echo "Run: cd tradekit && python3.11 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
  }
}

start_service() {
  local name="$1"
  local port="$2"
  local workdir="$3"
  shift 3

  local existing_pid
  existing_pid="$(port_pid "$port")"
  if [[ -n "$existing_pid" ]]; then
    echo "$name already listening on port $port (pid $existing_pid)"
    echo "$existing_pid" >"$(pid_file "$name")"
    return
  fi

  local log
  log="$(log_file "$name")"
  echo "Starting $name on port $port ..."
  (
    cd "$workdir"
    nohup "$@" >"$log" 2>&1 &
    echo $! >"$(pid_file "$name")"
  )
}

wait_http() {
  local name="$1"
  local url="$2"
  local tries="${3:-30}"

  for _ in $(seq 1 "$tries"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name ready: $url"
      return
    fi
    sleep 1
  done

  echo "$name did not become ready in ${tries}s: $url"
  echo "Last log lines:"
  tail -n 30 "$(log_file "$name")" 2>/dev/null || true
  exit 1
}

start_all() {
  check_backend
  check_frontend
  check_tradekit

  start_service \
    backend \
    "$BACKEND_PORT" \
    "$ROOT_DIR/backend" \
    "$ROOT_DIR/backend/venv/bin/python" -m app.main

  start_service \
    tradekit \
    "$TRADEKIT_PORT" \
    "$ROOT_DIR/tradekit" \
    "$ROOT_DIR/tradekit/.venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port "$TRADEKIT_PORT"

  start_service \
    frontend \
    "$FRONTEND_PORT" \
    "$ROOT_DIR/frontend" \
    npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT"

  wait_http backend "http://127.0.0.1:${BACKEND_PORT}/health" 45
  wait_http tradekit "http://127.0.0.1:${TRADEKIT_PORT}/health" 30
  wait_http frontend "http://127.0.0.1:${FRONTEND_PORT}/" 30

  echo
  echo "All services are running."
  echo "Frontend: http://127.0.0.1:${FRONTEND_PORT}"
  echo "TradeKit page: http://127.0.0.1:${FRONTEND_PORT}/tradekit"
  echo "Backend API: http://127.0.0.1:${BACKEND_PORT}"
  echo "TradeKit API/UI: http://127.0.0.1:${TRADEKIT_PORT}/ui/"
}

stop_one() {
  local name="$1"
  local port="$2"
  local pid
  pid="$(service_pid "$name")"

  if is_pid_running "$pid"; then
    echo "Stopping $name pid $pid ..."
    kill "$pid" 2>/dev/null || true
  fi

  local port_owner
  port_owner="$(port_pid "$port")"
  if [[ -n "$port_owner" ]]; then
    echo "Stopping $name port owner pid $port_owner ..."
    kill "$port_owner" 2>/dev/null || true
  fi

  rm -f "$(pid_file "$name")"
}

stop_all() {
  stop_one frontend "$FRONTEND_PORT"
  stop_one tradekit "$TRADEKIT_PORT"
  stop_one backend "$BACKEND_PORT"
  sleep 1
  echo "Stopped dev services."
}

status_one() {
  local name="$1"
  local port="$2"
  local pid
  pid="$(port_pid "$port")"
  if [[ -n "$pid" ]]; then
    echo "$name: running on port $port (pid $pid)"
  else
    echo "$name: stopped (port $port free)"
  fi
}

status_all() {
  status_one backend "$BACKEND_PORT"
  status_one frontend "$FRONTEND_PORT"
  status_one tradekit "$TRADEKIT_PORT"
}

show_logs() {
  echo "Logs in $LOG_DIR"
  ls -1 "$LOG_DIR" 2>/dev/null || true
  echo
  echo "Tail backend:"
  tail -n 20 "$(log_file backend)" 2>/dev/null || true
  echo
  echo "Tail frontend:"
  tail -n 20 "$(log_file frontend)" 2>/dev/null || true
  echo
  echo "Tail tradekit:"
  tail -n 20 "$(log_file tradekit)" 2>/dev/null || true
}

case "${1:-}" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    status_all
    ;;
  logs)
    show_logs
    ;;
  *)
    usage
    exit 1
    ;;
esac
