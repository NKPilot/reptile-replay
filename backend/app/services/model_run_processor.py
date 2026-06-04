"""Background model-clipping task orchestration."""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .video_processor import get_video, import_source_video, process_video

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
MODEL_RUNS_DIR = PROJECT_ROOT / "data" / "model_runs"
RESULTS_DIR = PROJECT_ROOT / "data" / "results" / "model_runs"
EVENTS_DIR = PROJECT_ROOT / "data" / "events"
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "locateanything-3b"


def init_model_run_storage():
    MODEL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _run_path(run_id: str) -> Path:
    safe = Path(run_id).name
    return MODEL_RUNS_DIR / f"{safe}.json"


def _read_json(path: Path) -> dict[str, Any]:
    with open(path) as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _write_run(record: dict[str, Any]):
    init_model_run_storage()
    path = _run_path(record["run_id"])
    with open(path, "w") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)


def get_model_run(run_id: str) -> dict[str, Any] | None:
    path = _run_path(run_id)
    if not path.exists():
        return None
    return _read_json(path)


def list_model_runs(video_id: str | None = None) -> list[dict[str, Any]]:
    init_model_run_storage()
    records = []
    for path in sorted(MODEL_RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            record = _read_json(path)
        except json.JSONDecodeError:
            continue
        if video_id and record.get("video_id") != video_id:
            continue
        records.append(_summarize_run(record))
    return records


def create_model_run(video_id: str | None = None, source_video_id: str | None = None) -> dict[str, Any]:
    init_model_run_storage()
    if not video_id and not source_video_id:
        raise ValueError("video_id 或 source_video_id 必须提供一个")

    if source_video_id and not video_id:
        video_id = import_source_video(source_video_id)

    video = get_video(video_id or "")
    if not video:
        raise FileNotFoundError(f"视频不存在: {video_id}")

    run_id = f"model_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    record = {
        "run_id": run_id,
        "video_id": video_id,
        "source_video_id": source_video_id or video.get("source_video_id", ""),
        "source_title": video.get("original_name", video_id),
        "status": "queued",
        "created_at": _now(),
        "started_at": "",
        "finished_at": "",
        "error": "",
        "clip_count": 0,
        "visible_clip_count": 0,
        "behavior_distribution": {},
        "result_path": str((RESULTS_DIR / f"{run_id}.json").relative_to(PROJECT_ROOT)),
    }
    _write_run(record)
    return record


def execute_model_run(run_id: str):
    record = get_model_run(run_id)
    if not record:
        return

    started = time.perf_counter()
    record["status"] = "running"
    record["started_at"] = _now()
    _write_run(record)

    try:
        video_id = record["video_id"]
        process_result = process_video(video_id)
        if process_result.get("error"):
            raise RuntimeError(process_result["error"])

        clips_dir = EVENTS_DIR / video_id
        if not clips_dir.exists() or not list(clips_dir.glob("*.mp4")):
            raise RuntimeError("没有生成候选剪辑")

        output = RESULTS_DIR / f"{run_id}.json"
        preview_dir = RESULTS_DIR / f"{run_id}_preview"
        cmd = [
            "uv",
            "run",
            "--locked",
            "--group",
            "locateanything",
            "python",
            str(PROJECT_ROOT / "scripts" / "locate_clips.py"),
            "--model-dir",
            str(DEFAULT_MODEL_DIR),
            "--backend",
            "locateanything",
            "--clips-dir",
            str(clips_dir),
            "--sample-frames",
            "3",
            "--limit",
            "0",
            "--output",
            str(output),
            "--preview-dir",
            str(preview_dir),
        ]
        completed = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(stderr or "模型检测失败")

        result = _read_json(output)
        clips = result.get("clips") if isinstance(result.get("clips"), list) else []
        visible = _visible_clips(clips)
        distribution = Counter(str(clip.get("auto_label", "unknown")) for clip in visible)

        record.update(
            {
                "status": "done",
                "finished_at": _now(),
                "error": "",
                "clip_count": len(clips),
                "visible_clip_count": len(visible),
                "behavior_distribution": dict(distribution.most_common()),
                "duration_seconds": round(time.perf_counter() - started, 1),
            }
        )
        _write_run(record)
    except Exception as exc:
        record.update(
            {
                "status": "failed",
                "finished_at": _now(),
                "error": str(exc),
                "duration_seconds": round(time.perf_counter() - started, 1),
            }
        )
        _write_run(record)


def _visible_clips(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    visible = [
        clip
        for clip in clips
        if clip.get("has_reptile") and clip.get("auto_label") and clip.get("auto_label") != "unknown"
    ]
    return sorted(visible, key=lambda clip: float(clip.get("confidence") or 0), reverse=True)


def _summarize_run(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": record.get("run_id", ""),
        "video_id": record.get("video_id", ""),
        "source_video_id": record.get("source_video_id", ""),
        "source_title": record.get("source_title", ""),
        "status": record.get("status", "queued"),
        "created_at": record.get("created_at", ""),
        "started_at": record.get("started_at", ""),
        "finished_at": record.get("finished_at", ""),
        "error": record.get("error", ""),
        "clip_count": int(record.get("clip_count") or 0),
        "visible_clip_count": int(record.get("visible_clip_count") or 0),
        "behavior_distribution": record.get("behavior_distribution", {}),
        "duration_seconds": float(record.get("duration_seconds") or 0),
    }


def load_model_run_detail(run_id: str) -> dict[str, Any] | None:
    record = get_model_run(run_id)
    if not record:
        return None

    detail = _summarize_run(record)
    result_path = PROJECT_ROOT / str(record.get("result_path", ""))
    clips: list[dict[str, Any]] = []
    if result_path.exists():
        result = _read_json(result_path)
        raw_clips = result.get("clips") if isinstance(result.get("clips"), list) else []
        clips = _visible_clips([clip for clip in raw_clips if isinstance(clip, dict)])

    detail["clips"] = [_normalize_clip(clip) for clip in clips]
    return detail


def _static_url_for_project_path(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        try:
            rel = path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return None
    else:
        rel = path.as_posix()

    if rel.startswith("data/events/"):
        return f"/static/events/{rel.removeprefix('data/events/')}"
    if rel.startswith("data/results/"):
        return f"/static/results/{rel.removeprefix('data/results/')}"
    if rel.startswith("data/clips/"):
        return f"/static/clips/{rel.removeprefix('data/clips/')}"
    return None


def _normalize_clip(clip: dict[str, Any]) -> dict[str, Any]:
    frames = clip.get("frames") if isinstance(clip.get("frames"), list) else []
    return {
        **clip,
        "clip_url": _static_url_for_project_path(clip.get("clip_path")),
        "frames": [
            {
                **frame,
                "preview_url": _static_url_for_project_path(frame.get("preview")),
            }
            for frame in frames
            if isinstance(frame, dict)
        ],
    }
