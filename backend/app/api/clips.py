"""
Clips API — 已处理剪辑片段的聚合查询

提供：筛选结果 + 运动标注 + 母视频信息 的三合一视图
"""

import csv
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # repo root
CLIPS_DIR = PROJECT_ROOT / "data" / "clips"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
ANNOTATIONS_DIR = PROJECT_ROOT / "data" / "annotations"

router = APIRouter(prefix="/api/clips", tags=["clips"])

LABEL_CN = {
    "resting": "静止/休息",
    "moving": "普通移动",
    "feeding_or_strike": "进食/捕食",
    "shedding": "疑似蜕皮",
    "contact_mating_like": "接触/疑似交配",
    "unknown": "未知",
}


def _load_screen_results() -> dict:
    """加载筛选结果 CSV → {relative_clip_path: 筛选字段}"""
    csv_path = CLIPS_DIR / "screen_result.csv"
    if not csv_path.exists():
        return {}
    results = {}
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # row["clip_path"] e.g. "data/clips/cmqwcb1fh_0/cmqwcb1fh_0_00000.mp4"
            rel = row["clip_path"].removeprefix("data/clips/").lstrip("/")
            results[rel] = row
    return results


def _load_auto_labels() -> dict:
    """加载所有标注 CSV → {relative_clip_path: 标注字段}"""
    labels = {}
    if not ANNOTATIONS_DIR.exists():
        return labels
    for csv_path in sorted(ANNOTATIONS_DIR.glob("*_labels.csv")):
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # row["clip_path"] is absolute → 转为相对路径
                abs_path = row.get("clip_path", "")
                rel = abs_path.removeprefix(str(CLIPS_DIR)).lstrip("/")
                if rel:
                    labels[rel] = row
    return labels


def _load_source_videos() -> dict:
    """加载母视频的 .info.json → {video_id: {title, uploader, duration, webpage_url, thumbnail}}"""
    sources = {}
    if not RAW_DIR.exists():
        return sources
    for info_file in sorted(RAW_DIR.glob("*/*.info.json")):
        video_id = info_file.parent.name
        try:
            with open(info_file) as f:
                info = json.load(f)
            sources[video_id] = {
                "video_id": video_id,
                "title": info.get("title", video_id),
                "uploader": info.get("uploader", ""),
                "duration": info.get("duration", 0),
                "webpage_url": info.get("webpage_url", ""),
                "thumbnail": info.get("thumbnail", ""),
            }
        except (json.JSONDecodeError, KeyError):
            continue
    return sources


@router.get("/")
async def list_clips(
    classification: Optional[str] = Query(None, description="筛选分类: usable / unknown / bad"),
    label: Optional[str] = Query(None, description="行为标签过滤: feeding_or_strike / resting / moving / ..."),
    video_id: Optional[str] = Query(None, description="按母视频 ID 过滤"),
    limit: int = Query(200, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    """
    返回所有已处理 clip 的聚合列表，每条包含：
    - 筛选信息（usable/unknown/bad, 模糊度, 运动值...）
    - 运动标注（resting/moving/feeding_or_strike/...）
    - 母视频信息（标题, 上传者, YouTube 链接, 封面）
    """
    screen = _load_screen_results()
    labels = _load_auto_labels()
    sources = _load_source_videos()

    clips = []
    for rel_path, scr in screen.items():
        # 提取 video_id
        parts = rel_path.split("/")
        vid = parts[0] if parts else "unknown"

        # 跳过不符合过滤条件的
        if classification and scr.get("classification") != classification:
            continue
        if video_id and vid != video_id:
            continue

        # 标注信息
        lbl = labels.get(rel_path, {})
        auto_label = lbl.get("auto_label", "unknown")
        label_cn = lbl.get("label_cn", LABEL_CN.get(auto_label, "未知"))
        confidence = float(lbl.get("confidence", 0))

        if label and auto_label != label:
            continue

        # 母视频信息
        src = sources.get(vid)

        clips.append({
            "clip_path": rel_path,
            "video_id": vid,
            "clip_name": Path(rel_path).stem,
            # 筛选字段
            "classification": scr.get("classification", "unknown"),
            "score": int(scr.get("score", 0)),
            "avg_blur": float(scr.get("avg_blur", 0)),
            "avg_motion": float(scr.get("avg_motion", 0)),
            "peak_motion": float(scr.get("peak_motion", 0)),
            "reasons": scr.get("reasons", ""),
            # 标注字段
            "auto_label": auto_label,
            "label_cn": label_cn,
            "confidence": round(confidence, 2),
            # 母视频
            "source_video": src,
            # 播放 URL
            "clip_url": f"/static/clips/{rel_path}",
        })

    total = len(clips)
    clips = clips[offset: offset + limit]

    # 统计
    cls_counts = {}
    lbl_counts = {}
    for c in screen.values():
        cls_counts[c.get("classification", "unknown")] = cls_counts.get(c.get("classification", "unknown"), 0) + 1
    for l in labels.values():
        al = l.get("auto_label", "unknown")
        lbl_counts[al] = lbl_counts.get(al, 0) + 1

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "clips": clips,
        "stats": {
            "by_classification": cls_counts,
            "by_label": {
                k: v for k, v in {
                    **{lab: lbl_counts.get(lab, 0) for lab in LABEL_CN},
                }.items() if v > 0
            },
            "total_source_videos": len(sources),
            "total_clips_with_labels": len(labels),
        },
    }


@router.get("/sources")
async def list_sources():
    """列出所有母视频摘要"""
    sources = _load_source_videos()
    screen = _load_screen_results()

    result = []
    for vid, src in sources.items():
        usable = sum(1 for p, s in screen.items() if p.startswith(vid + "/") and s.get("classification") == "usable")
        unknown = sum(1 for p, s in screen.items() if p.startswith(vid + "/") and s.get("classification") == "unknown")
        result.append({
            **src,
            "usable_clips": usable,
            "unknown_clips": unknown,
            "total_clips": usable + unknown,
        })

    return {"sources": sorted(result, key=lambda x: -x["total_clips"])}
