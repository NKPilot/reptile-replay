#!/bin/bash
# ReptiReplay 一键启动脚本
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# 确保 PATH 包含 ~/.local/bin（uv 和 ffmpeg 可能在这里）
export PATH="$HOME/.local/bin:$PATH"

echo "========================================"
echo "  ReptiReplay - 爬宠行为回放系统"
echo "========================================"

# 1. 检查 uv + Python 依赖
echo ""
echo "[1/4] 检查 Python 依赖 (uv)..."
if ! command -v uv &>/dev/null; then
    echo "  安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
uv sync
echo "  ✓ Python 依赖就绪"

# 2. 检查 ffmpeg
echo "[2/4] 检查 ffmpeg..."
if ! command -v ffmpeg &>/dev/null; then
    echo "  安装 ffmpeg 静态版本..."
    curl -sSL -o /tmp/ffmpeg.tar.xz "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
    tar xf /tmp/ffmpeg.tar.xz -C /tmp/
    cp /tmp/ffmpeg-*-static/ffmpeg /tmp/ffmpeg-*-static/ffprobe ~/.local/bin/
fi
echo "  ✓ ffmpeg 就绪"

# 3. 前端安装
echo "[3/4] 安装前端依赖..."
cd "$PROJECT_DIR/frontend"
npm install --silent 2>&1 | tail -1
echo "  ✓ 前端依赖就绪"

# 4. 启动
echo "[4/4] 启动服务..."
echo ""

# 启动后端 (FastAPI via uv run)
cd "$PROJECT_DIR"
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
echo "  后端: http://localhost:8000 (PID: $BACKEND_PID)"

# 启动前端 (Vite)
cd "$PROJECT_DIR/frontend"
npx vite --host 0.0.0.0 --port 5173 &
FRONTEND_PID=$!
echo "  前端: http://localhost:5173 (PID: $FRONTEND_PID)"

echo ""
echo "========================================"
echo "  ✅ ReptiReplay 已启动!"
echo ""
echo "  前端页面:  http://localhost:5173"
echo "  API 文档:  http://localhost:8000/docs"
echo ""
echo "  按 Ctrl+C 停止所有服务"
echo "========================================"

# 等待
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo '已停止'" EXIT
wait
