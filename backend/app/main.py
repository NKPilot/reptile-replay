"""
爬宠关键行为识别与自动剪辑系统 — FastAPI 主入口
"""

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 确保路径
BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))  # 让 from app import ... 可用
sys.path.insert(0, str(PROJECT_ROOT))

# 确保 ffmpeg/yt-dlp 在 PATH 中
os.environ["PATH"] = os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")

from app.api import videos, events, clips
from app.services.video_processor import init_storage

app = FastAPI(
    title="ReptiReplay - 爬宠关键行为识别与自动剪辑",
    description="自动从长视频中发现疑似爬宠关键行为，并剪辑出前后片段",
    version="0.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
app.include_router(videos.router)
app.include_router(events.router)
app.include_router(clips.router)

# 静态文件服务（剪辑片段）
events_dir = PROJECT_ROOT / "data" / "events"
events_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/events", StaticFiles(directory=str(events_dir)), name="static_events")

# 上传文件服务
uploads_dir = PROJECT_ROOT / "data" / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=str(uploads_dir)), name="static_uploads")

# 剪辑片段静态服务
clips_dir = PROJECT_ROOT / "data" / "clips"
clips_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/clips", StaticFiles(directory=str(clips_dir)), name="static_clips")


@app.on_event("startup")
async def startup():
    init_storage()
    print("🚀 ReptiReplay 后端已启动")


@app.get("/")
async def root():
    return {
        "name": "ReptiReplay",
        "version": "0.1.0",
        "description": "爬宠关键行为识别与自动剪辑系统",
    }


@app.get("/api/health")
async def health():
    return {"status": "ok"}
