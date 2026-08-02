#!/bin/bash
set -e

# ============================================================
# 宝妈指数 — Docker 容器入口
# ============================================================

# 将包路径加入 PYTHONPATH（部署工具生成的 Dockerfile 只设了 /app）
export PYTHONPATH="/app/src:$PYTHONPATH"

# 数据输出目录（映射到宿主机 ./output）
export MOM_INDEX_DATA_DIR="/app/output/data"
mkdir -p "$MOM_INDEX_DATA_DIR"

cd /app

# ===== 运行管线 =====
echo "========================================================"
echo "  👩‍👧 宝妈指数 · 数据采集与分析"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"
python -m mom_index.pipeline

# ===== 同步数据到前端目录 =====
echo ""
echo "📂 同步数据到前端目录..."
mkdir -p /app/output/frontend/data
cp /app/output/data/*.json /app/output/frontend/data/ 2>/dev/null || true

# 复制前端静态文件
cp -r /app/src/mom_index/frontend/* /app/output/frontend/ 2>/dev/null || true
echo "  前端文件已就绪"

# ===== 定时任务模式 =====
if [ -n "$CRON_SCHEDULE" ]; then
    echo ""
    echo "⏰ 定时任务模式: $CRON_SCHEDULE"
    echo "$CRON_SCHEDULE cd /app && MOM_INDEX_DATA_DIR=/app/output/data python -m mom_index.pipeline" > /app/crontab
    exec supercronic /app/crontab
fi

# ===== HTTP 服务模式 =====
PORT=${WEBSERVER_PORT:-8080}
PORT=${WEBSERVER_PORT:-8503}
echo ""
echo "🌐 启动 Web 服务, 端口 $PORT"
echo "   访问 http://localhost:$PORT/dashboard.html"
echo ""
cd /app/output/frontend
exec python -m http.server "$PORT"
