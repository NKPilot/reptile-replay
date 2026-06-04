"""LocateAnything offline result browsing API."""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "data" / "results"
CLIPS_DIR = PROJECT_ROOT / "data" / "clips"
EVENTS_DIR = PROJECT_ROOT / "data" / "events"

router = APIRouter(prefix="/api/locator", tags=["locator"])


def _safe_json_path(run_id: str) -> Path:
    name = Path(run_id).name
    if not name.endswith(".json"):
        name = f"{name}.json"
    path = RESULTS_DIR / name
    if path.parent != RESULTS_DIR:
        raise HTTPException(400, "非法结果文件名")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"结果 JSON 无法解析: {path.name}") from exc
    if not isinstance(data, dict):
        raise HTTPException(500, f"结果 JSON 格式不正确: {path.name}")
    return data


def _is_locator_result(data: dict[str, Any]) -> bool:
    return "clips" in data and ("model_dir" in data or "backend" in data or "prompts" in data)


def _result_files() -> list[Path]:
    if not RESULTS_DIR.exists():
        return []
    files = []
    for path in RESULTS_DIR.glob("*.json"):
        try:
            data = _read_json(path)
        except HTTPException:
            continue
        if _is_locator_result(data):
            files.append(path)
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _static_url_for_project_path(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        rel = path.as_posix()
    else:
        try:
            rel = path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return None

    if rel.startswith("data/clips/"):
        return f"/static/clips/{rel.removeprefix('data/clips/')}"
    if rel.startswith("data/events/"):
        return f"/static/events/{rel.removeprefix('data/events/')}"
    if rel.startswith("data/results/"):
        return f"/static/results/{rel.removeprefix('data/results/')}"
    return None


def _summarize_run(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    clips = data.get("clips") if isinstance(data.get("clips"), list) else []
    detected = int(data.get("detected_clip_count") or sum(1 for c in clips if c.get("has_reptile")))
    return {
        "run_id": path.stem,
        "filename": path.name,
        "created_at": data.get("created_at", ""),
        "model_dir": data.get("model_dir", ""),
        "backend": data.get("backend", ""),
        "device": data.get("device", ""),
        "dtype": data.get("dtype", ""),
        "prompts": data.get("prompts", []),
        "sample_frames": data.get("sample_frames", 0),
        "elapsed_sec": data.get("elapsed_sec", 0),
        "clip_count": int(data.get("clip_count") or len(clips)),
        "detected_clip_count": detected,
    }


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


@router.get("/runs")
async def list_locator_runs():
    """List offline LocateAnything/GroundingDINO result JSON files."""
    runs = [_summarize_run(path, _read_json(path)) for path in _result_files()]
    return {"runs": runs}


@router.get("/runs/{run_id}")
async def get_locator_run(run_id: str):
    """Return a normalized model-detection run for frontend review."""
    path = _safe_json_path(run_id)
    if not path.exists():
        raise HTTPException(404, "模型检测结果不存在")

    data = _read_json(path)
    if not _is_locator_result(data):
        raise HTTPException(400, "该 JSON 不是模型检测结果")

    clips = data.get("clips") if isinstance(data.get("clips"), list) else []
    summary = _summarize_run(path, data)
    return {
        **summary,
        "clips": [_normalize_clip(clip) for clip in clips if isinstance(clip, dict)],
    }
