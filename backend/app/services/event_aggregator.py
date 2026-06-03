"""
事件聚合器 v2 —— 从运动曲线生成行为事件。

改进:
    - 增强置信度公式（与 auto_label.py v2 对齐）
    - 自适应阈值（基于全视频运动基线）
    - 限制: 不包含光流/纹理分析（实时处理阶段无逐帧光流数据）

流程:
    滑动窗口 → 窗口级分类 → 连续同类窗口合并 → 添加前后缓冲 → 生成事件
"""

from typing import List, Optional
from .motion_detector import analyze_video_motion
from pathlib import Path


# 行为分类规则 (v2 对齐)
CLASSIFY_RULES = {
    "resting": {
        "max_avg_intensity": 0.02,
        "max_motion_ratio": 0.3,
    },
    "moving": {
        "min_avg_intensity": 0.02,
        "max_avg_intensity": 0.15,
        "min_motion_ratio": 0.4,
    },
    "feeding_or_strike": {
        "min_peak_intensity": 0.15,
        "peak_to_avg_ratio": 2.5,
        "max_peak_duration_ratio": 0.3,
    },
    "contact_mating_like": {
        "min_avg_regions": 1.5,
        "min_overlap_ratio": 0.2,
    },
    "shedding": {
        "min_avg_intensity": 0.02,
        "max_avg_intensity": 0.08,
        "min_motion_ratio": 0.6,
    },
}


def classify_window(window: list[dict], baseline_motion: float = 0.002) -> tuple:
    """
    对滑动窗口内的运动数据分类（v2 增强置信度）。

    参数:
        window: 窗口内帧数据列表
        baseline_motion: 全局运动基线（用于自适应归一化）

    返回: (label_en, confidence)
    """
    if not window:
        return "unknown", 0.0

    intensities = [w["intensity"] for w in window if w.get("intensity", 0) > 0]
    regions = [w.get("num_regions", 0) for w in window]

    if not intensities:
        return "resting", 0.9

    avg_intensity = sum(intensities) / len(intensities)
    peak_intensity = max(intensities)
    motion_ratio = sum(1 for i in intensities if i > 0.005) / len(intensities)
    avg_regions = sum(regions) / len(regions)
    overlap_ratio = sum(1 for r in regions if r >= 2) / max(len(regions), 1)
    peak_to_avg = peak_intensity / max(avg_intensity, 0.001)

    # 自适应归一化
    norm_avg = avg_intensity / max(baseline_motion, 0.001)
    norm_peak = peak_intensity / max(baseline_motion, 0.001)

    # 1. feeding_or_strike: 短时间剧烈运动（v2: 增强置信度公式）
    if (peak_intensity >= CLASSIFY_RULES["feeding_or_strike"]["min_peak_intensity"] and
            peak_to_avg >= CLASSIFY_RULES["feeding_or_strike"]["peak_to_avg_ratio"]):
        # v2: 结合峰值与峰均比计算置信度
        peak_score = min((peak_intensity - 0.15) / 0.3, 1.0)
        ratio_score = min((peak_to_avg - 2.5) / 5.0, 1.0)
        conf = 0.5 + peak_score * 0.25 + ratio_score * 0.15
        return "feeding_or_strike", round(min(conf, 0.92), 2)

    # 2. contact_mating_like: 多运动区域（v2: 增强置信度）
    if (avg_regions >= CLASSIFY_RULES["contact_mating_like"]["min_avg_regions"] and
            overlap_ratio >= CLASSIFY_RULES["contact_mating_like"]["min_overlap_ratio"]):
        region_score = min(avg_regions / 5.0, 1.0)
        conf = 0.4 + overlap_ratio * 0.3 + region_score * 0.15
        return "contact_mating_like", round(min(conf, 0.85), 2)

    # 3. shedding: 低速长时间运动（v2: 置信度上限提升到 0.60）
    r = CLASSIFY_RULES["shedding"]
    if r["min_avg_intensity"] <= avg_intensity <= r["max_avg_intensity"] and motion_ratio >= r["min_motion_ratio"]:
        # 低速程度评分：越接近下限越好
        speed_score = 1.0 - (avg_intensity - r["min_avg_intensity"]) / (r["max_avg_intensity"] - r["min_avg_intensity"])
        conf = min(motion_ratio * 0.4 + speed_score * 0.2, 0.60)  # v2: 上限 0.60
        return "shedding", round(conf, 2)

    # 4. moving: 持续中等强度运动
    r = CLASSIFY_RULES["moving"]
    if r["min_avg_intensity"] <= avg_intensity <= r["max_avg_intensity"] and motion_ratio >= r["min_motion_ratio"]:
        conf = min(motion_ratio * 0.7 + 0.1, 0.85)
        return "moving", round(conf, 2)

    # 5. resting
    if avg_intensity <= CLASSIFY_RULES["resting"]["max_avg_intensity"]:
        return "resting", round(0.9 - avg_intensity * 5, 2)

    return "unknown", 0.3


def generate_events(
    video_path: Path,
    window_size: float = 5.0,
    step_size: float = 2.0,
    min_conf: float = 0.45,
    min_consecutive: int = 2,
    merge_gap: float = 10.0,
    pre_buffer: float = 10.0,
    post_buffer: float = 20.0,
) -> dict:
    """
    从视频生成行为事件列表。

    参数:
        video_path: 视频路径
        window_size: 滑动窗口长度（秒）
        step_size: 步长（秒）
        min_conf: 最低置信度阈值
        min_consecutive: 连续多少窗口触发才算事件
        merge_gap: 相邻同类事件合并间隔（秒）
        pre_buffer: 事件前缓冲（秒）
        post_buffer: 事件后缓冲（秒）

    返回:
        {video_id, events: [...], motion_summary: {...}}
    """
    motion = analyze_video_motion(video_path)
    if "error" in motion:
        return {"error": motion["error"], "events": []}

    curve = motion["motion_curve"]
    duration = motion["video_duration"]
    fps_effective = len(curve) / max(duration, 1)

    # v2: 计算全视频运动基线
    all_intensities = [f.get("intensity", 0) for f in curve if f.get("intensity", 0) > 0.001]
    if len(all_intensities) >= 5:
        baseline_motion = max(sorted(all_intensities)[len(all_intensities) // 10], 0.002)
    else:
        baseline_motion = 0.002

    # 窗口内帧数
    window_frames = max(1, int(window_size * fps_effective))
    step_frames = max(1, int(step_size * fps_effective))

    # 滑动窗口分类
    window_labels = []
    for start in range(0, len(curve) - window_frames + 1, step_frames):
        window_data = curve[start:start + window_frames]
        label, conf = classify_window(window_data, baseline_motion)
        window_labels.append({
            "start_time": curve[start]["time"],
            "end_time": curve[min(start + window_frames - 1, len(curve) - 1)]["time"],
            "label": label,
            "confidence": conf,
        })

    # 筛选高置信度窗口
    candidates = [w for w in window_labels if w["confidence"] >= min_conf]

    # 连续同类窗口检测
    raw_events = []
    i = 0
    while i < len(candidates):
        label = candidates[i]["label"]
        # 跳过 resting 和 unknown（不属于"关键行为"）
        if label in ("resting", "unknown"):
            i += 1
            continue

        j = i
        while j < len(candidates) and candidates[j]["label"] == label:
            j += 1

        consecutive = j - i
        if consecutive >= min_consecutive:
            confidences = [c["confidence"] for c in candidates[i:j]]
            raw_events.append({
                "label": label,
                "start": candidates[i]["start_time"],
                "end": candidates[j - 1]["end_time"],
                "confidence": round(sum(confidences) / len(confidences), 2),
                "windows": consecutive,
            })

        i = j

    # 合并相邻同类事件
    merged_events = []
    for evt in raw_events:
        if not merged_events:
            merged_events.append(evt)
            continue

        last = merged_events[-1]
        if evt["label"] == last["label"] and (evt["start"] - last["end"]) <= merge_gap:
            last["end"] = evt["end"]
            last["confidence"] = round((last["confidence"] + evt["confidence"]) / 2, 2)
            last["windows"] += evt["windows"]
        else:
            merged_events.append(evt)

    # 添加前后缓冲，生成最终事件
    video_id = video_path.stem
    events = []
    for i, evt in enumerate(merged_events):
        clip_start = max(0, evt["start"] - pre_buffer)
        clip_end = min(duration, evt["end"] + post_buffer)

        events.append({
            "event_id": f"evt_{video_id}_{i:03d}",
            "video_id": video_id,
            "type": evt["label"],
            "label": _cn_label(evt["label"]),
            "label_en": evt["label"],
            "start": round(evt["start"], 2),
            "end": round(evt["end"], 2),
            "confidence": evt["confidence"],
            "clip_start": round(clip_start, 2),
            "clip_end": round(clip_end, 2),
            "status": "pending",
        })

    return {
        "video_id": video_id,
        "video_duration": duration,
        "events": events,
        "motion_summary": {
            "avg_intensity": motion["avg_intensity"],
            "peak_intensity": motion["peak_intensity"],
            "total_frames": motion["total_frames"],
        },
    }


def _cn_label(label_en: str) -> str:
    mapping = {
        "resting": "静止/休息",
        "moving": "普通移动",
        "feeding_or_strike": "疑似进食/捕食",
        "shedding": "疑似蜕皮",
        "contact_mating_like": "疑似交配/接触",
        "unknown": "未知",
    }
    return mapping.get(label_en, label_en)
