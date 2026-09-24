#!/usr/bin/env bash
# 启动整套服务，等 WebUI 就绪后（仅在有图形环境时）自动打开控制台。
# CI/CD 的 helper 不走这个脚本（服务器通常无图形环境），只做 compose build/up。
#
# 用法：./scripts/up.sh [--no-open] [compose up 的其他参数...]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

no_open=0
compose_args=()
for arg in "$@"; do
  case "$arg" in
    --no-open) no_open=1 ;;
    *) compose_args+=("$arg") ;;
  esac
done

docker compose up -d --build "${compose_args[@]+"${compose_args[@]}"}"

# WebUI 端口与 compose 插值同源（.env -> .env.prod）
port=18080
env_file=""
if [ -f .env ]; then env_file=.env
elif [ -f .env.prod ]; then env_file=.env.prod
fi
if [ -n "$env_file" ]; then
  v=$(sed -n 's/^WEBUI_HOST_PORT[[:space:]]*=[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$env_file" | tail -1)
  [ -n "$v" ] && port=$v
fi
url="http://localhost:${port}"

# 等 WebUI 健康就绪（最多约 90 秒；首次构建耗时已在上面的 up --build 结束）
ready=0
if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 45); do
    if curl -fsS --max-time 2 "$url/api/health" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
elif command -v wget >/dev/null 2>&1; then
  for _ in $(seq 1 45); do
    if wget -q -T 2 -O /dev/null "$url/api/health" 2>/dev/null; then
      ready=1
      break
    fi
    sleep 2
  done
else
  ready=1  # no http client to probe with: don't block on health
fi

if [ "$ready" != 1 ]; then
  echo "WebUI 尚未就绪，请查看容器日志: docker compose logs webui" >&2
  echo "$url"
  exit 1
fi
echo "WebUI 已就绪: $url"

# 只有图形会话（本地桌面，或 SSH -X 转发了 DISPLAY）且是交互式终端时才尝试
# 打开浏览器；SSH/无头服务器、cron/CI、自动更新触发一律跳过，只打印地址。
if [ "$no_open" = 1 ]; then
  exit 0
fi
# 非交互式（无 TTY：cron、systemd、CI、管道）不弹
if [ ! -t 0 ] || [ ! -t 1 ]; then
  exit 0
fi
# CI 环境变量存在时不弹
if [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
  exit 0
fi
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  exit 0
fi
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$url" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  open "$url" >/dev/null 2>&1 || true
fi
