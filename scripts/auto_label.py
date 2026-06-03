#!/usr/bin/env python3
"""
自动标注脚本 v2 —— 基于运动分析 + 光流方向 + 纹理检测对 usable clips 进行初步行为分类。

分类逻辑:
    resting          → 运动强度极低 + 无方向性
    moving           → 持续中等强度运动 + 方向较稳定
    feeding_or_strike  → 短时间剧烈运动峰值 + 高方向一致性（单向爆发）
    contact_mating_like → 多运动区域重叠 + 低方向一致性（多向交错）
    shedding         → 低速长时间运动 + 高纹理变化率 + 方向杂乱
    unknown          → 不满足以上条件

新增特征 (v2):
    - 光流方向分析: Farneback 稠密光流 → 方向一致性、主方向稳定性
    - 纹理变化检测: LBP 直方图帧间差异 → 辅助蜕皮识别
    - 自适应阈值: 按 clip 自身运动基线归一化阈值

用法:
    # 对筛选后的 usable clips 进行标注
    python auto_label.py --clips-dir data/clips/usable

    # 输出标注 CSV
    python auto_label.py --clips-dir data/clips/usable --output data/annotations/auto_labels.csv

    # 详细输出
    python auto_label.py --clips-dir data/clips --verbose

输出:
    data/annotations/auto_labels.csv
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "configs" / "labels.yaml"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# ============================================================
# 辅助视觉特征函数
# ============================================================

def _compute_lbp(gray: np.ndarray) -> np.ndarray:
    """
    计算灰度图的 Local Binary Pattern (LBP)，使用 8 邻域。
    返回与输入同尺寸的 LBP 码图（边缘裁掉 1px）。
    """
    h, w = gray.shape
    lbp = np.zeros((h - 2, w - 2), dtype=np.uint8)
    center = gray[1:h - 1, 1:w - 1]

    # 8 个邻域偏移
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, 1),
               (1, 1), (1, 0), (1, -1), (0, -1)]

    for i, (dy, dx) in enumerate(offsets):
        neighbor = gray[1 + dy:h - 1 + dy, 1 + dx:w - 1 + dx]
        lbp |= ((neighbor >= center).astype(np.uint8) << i)

    return lbp


def _lbp_histogram_distance(lbp1: np.ndarray, lbp2: np.ndarray) -> float:
    """
    比较两帧 LBP 图的直方图差异（卡方距离）。
    返回值越高表示纹理变化越大。
    """
    bins = 256
    hist1 = np.histogram(lbp1.ravel(), bins=bins, range=(0, 255))[0].astype(np.float32)
    hist2 = np.histogram(lbp2.ravel(), bins=bins, range=(0, 255))[0].astype(np.float32)

    # 归一化
    s1 = hist1.sum()
    s2 = hist2.sum()
    if s1 == 0 or s2 == 0:
        return 0.0
    hist1 /= s1
    hist2 /= s2

    # 卡方距离
    diff = hist1 - hist2
    total = hist1 + hist2 + 1e-10
    chi2 = np.sum(diff * diff / total)
    return float(chi2)


def _circular_mean_resultant_length(angles: np.ndarray) -> float:
    """
    计算角度分布的平均合向量长度 R (0~1)。
    R → 1: 方向高度一致
    R → 0: 方向完全随机
    """
    if len(angles) == 0:
        return 0.0
    c = np.mean(np.cos(angles))
    s = np.mean(np.sin(angles))
    return float(np.sqrt(c * c + s * s))


def _dominant_direction_stability(mags: np.ndarray, angles: np.ndarray) -> float:
    """
    计算主方向稳定性：最大方向扇区占比。
    将角度分为 8 个扇区，看最大扇区的占比。
    返回 0~1，越高表示运动始终朝一个方向。
    """
    if len(angles) == 0:
        return 0.0
    bins = np.linspace(-np.pi, np.pi, 9)
    hist, _ = np.histogram(angles, bins=bins, weights=mags)
    total = hist.sum()
    if total == 0:
        return 0.0
    return float(hist.max() / total)


# ============================================================
# 运动特征提取（增强版）
# ============================================================

def extract_motion_profile(
    clip_path: Path,
    flow_params: dict,
    texture_params: dict,
) -> dict:
    """
    提取 clip 的完整运动特征（v2 增强版）。

    新增:
        - 光流方向一致性          direction_consistency (0~1)
        - 主方向稳定性             dominant_direction_stability (0~1)
        - 平均纹理变化率           texture_change_rate (0~1)
        - 运动基线 (自适应阈值)    baseline_motion
        - 归一化后平均强度         norm_avg_intensity

    返回:
        {
            "total_frames": int,
            "motion_curve": [float],
            "magnitude_curve": [float],
            "region_counts": [int],
            "avg_intensity": float,
            "peak_intensity": float,
            "peak_sustained_ratio": float,
            "motion_frame_ratio": float,
            "max_regions": int,
            "overlap_frames": int,
            # v2 新增
            "direction_consistency": float,
            "dominant_direction_stability": float,
            "texture_change_rate": float,
            "baseline_motion": float,
            "norm_avg_intensity": float,
            "norm_peak_intensity": float,
        }
    """
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        return {"total_frames": 0}

    ds_ratio = flow_params.get("downsample_ratio", 0.5)
    min_flow_mag = flow_params.get("min_flow_magnitude", 0.5)
    t_sub = texture_params.get("texture_subsample", 4)

    motion_curve = []
    magnitude_curve = []
    region_counts = []
    prev_frame = None
    prev_gray_full = None

    # 光流方向收集
    all_flow_angles: List[float] = []
    all_flow_mags: List[float] = []

    # 纹理变化率收集
    texture_changes: List[float] = []
    prev_lbp = None
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        gray_full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_full = cv2.GaussianBlur(gray_full, (5, 5), 0)

        # ---- 运动强度 (帧差法) ----
        if prev_frame is not None:
            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            curr_gray = gray_full
            prev_gray = cv2.GaussianBlur(prev_gray, (5, 5), 0)

            diff = cv2.absdiff(prev_gray, curr_gray)
            _, thresh = cv2.threshold(diff, 15, 255, cv2.THRESH_BINARY)

            total_pixels = thresh.shape[0] * thresh.shape[1]
            motion_pixels = np.count_nonzero(thresh)
            intensity = motion_pixels / total_pixels
            magnitude = np.mean(diff) / 255.0

            # 连通域分析
            num_regions = 0
            if motion_pixels > 100:
                kernel = np.ones((3, 3), np.uint8)
                cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
                num_labels, _ = cv2.connectedComponents(cleaned)
                num_regions = max(0, num_labels - 1)

            motion_curve.append(intensity)
            magnitude_curve.append(magnitude)
            region_counts.append(num_regions)

        # ---- 光流方向 (Farneback) ----
        if prev_gray_full is not None:
            h, w = gray_full.shape
            ds_size = (int(w * ds_ratio), int(h * ds_ratio))
            prev_small = cv2.resize(prev_gray_full, ds_size)
            curr_small = cv2.resize(gray_full, ds_size)

            flow = cv2.calcOpticalFlowFarneback(
                prev_small, curr_small, None,
                0.5, 3, 15, 3, 5, 1.2, 0
            )
            mag, ang = cv2.cartToPolar(flow[..., 0], flow[..., 1])

            # 过滤掉太小的光流向量（噪声）
            mask = mag > min_flow_mag
            if mask.any():
                valid_angles = ang[mask].ravel()
                valid_mags = mag[mask].ravel()
                all_flow_angles.extend(valid_angles.tolist())
                all_flow_mags.extend(valid_mags.tolist())

        # ---- 纹理变化 (LBP) ----
        if frame_idx % t_sub == 0:
            curr_lbp = _compute_lbp(gray_full)
            if prev_lbp is not None:
                tex_change = _lbp_histogram_distance(prev_lbp, curr_lbp)
                texture_changes.append(tex_change)
            prev_lbp = curr_lbp

        prev_frame = frame
        prev_gray_full = gray_full
        frame_idx += 1

    cap.release()

    total_frames = len(motion_curve)
    if total_frames == 0:
        return {"total_frames": 0}

    avg_intensity = float(np.mean(motion_curve))
    peak_intensity = float(max(motion_curve))

    # 峰值持续时间占比
    peak_threshold = max(avg_intensity * 2.0, 0.3)
    peak_frames = sum(1 for v in motion_curve if v > peak_threshold)
    peak_ratio = peak_frames / total_frames

    # 有运动帧占比
    motion_frames = sum(1 for v in motion_curve if v > 0.01)
    motion_ratio = motion_frames / total_frames

    # 多区域重叠帧数
    overlap_frames = sum(1 for r in region_counts if r >= 2)

    # ---- v2 新增特征 ----

    # 方向一致性
    all_flow_angles_arr = np.array(all_flow_angles, dtype=np.float64)
    all_flow_mags_arr = np.array(all_flow_mags, dtype=np.float64)
    direction_consistency = _circular_mean_resultant_length(all_flow_angles_arr)
    dominant_dir_stability = _dominant_direction_stability(all_flow_mags_arr, all_flow_angles_arr)

    # 纹理变化率
    texture_change_rate = float(np.mean(texture_changes)) if texture_changes else 0.0

    # ---- 自适应基线 ----
    # 取运动曲线最低 N% 的帧估计运动基线（排除零运动帧）
    motion_arr = np.array(motion_curve)
    nonzero = motion_arr[motion_arr > 0.001]
    if len(nonzero) >= 3:
        baseline_motion = float(np.percentile(nonzero, 20))
    else:
        baseline_motion = avg_intensity * 0.3

    baseline_motion = max(baseline_motion, 0.002)  # 防止基线太低

    # 归一化强度 = 原始强度 / 基线
    norm_avg = avg_intensity / baseline_motion if baseline_motion > 0 else avg_intensity
    norm_peak = peak_intensity / baseline_motion if baseline_motion > 0 else peak_intensity

    return {
        "total_frames": total_frames,
        "motion_curve": motion_curve,
        "magnitude_curve": magnitude_curve,
        "region_counts": region_counts,
        "avg_intensity": round(avg_intensity, 6),
        "peak_intensity": round(peak_intensity, 6),
        "peak_sustained_ratio": round(peak_ratio, 4),
        "motion_frame_ratio": round(motion_ratio, 4),
        "max_regions": max(region_counts) if region_counts else 0,
        "overlap_frames": overlap_frames,
        # v2 新增
        "direction_consistency": round(direction_consistency, 4),
        "dominant_direction_stability": round(dominant_dir_stability, 4),
        "texture_change_rate": round(texture_change_rate, 4),
        "baseline_motion": round(baseline_motion, 6),
        "norm_avg_intensity": round(norm_avg, 4),
        "norm_peak_intensity": round(norm_peak, 4),
    }


# ============================================================
# 行为分类（增强版）
# ============================================================

def classify_behavior(profile: dict, rules: dict) -> Tuple[str, float, str]:
    """
    根据运动 + 光流 + 纹理特征进行行为分类（v2 增强版）。

    返回: (label, confidence, reason)
    """
    if profile.get("total_frames", 0) == 0:
        return "unknown", 0.0, "无法读取视频"

    r = rules
    adaptive_cfg = r.get("adaptive", {})
    use_adaptive = adaptive_cfg.get("enable", True)

    # 根据自适应开关选择用原始值还是归一化值
    if use_adaptive and profile.get("norm_avg_intensity", 0) > 0:
        avg = profile["norm_avg_intensity"]
        peak = profile["norm_peak_intensity"]
        adapt_tag = "(自适应)"
    else:
        avg = profile["avg_intensity"]
        peak = profile["peak_intensity"]
        adapt_tag = ""

    # 原始值仍用于部分判断
    avg_raw = profile["avg_intensity"]
    peak_raw = profile["peak_intensity"]
    peak_ratio = profile["peak_sustained_ratio"]
    motion_ratio = profile["motion_frame_ratio"]
    max_regions = profile["max_regions"]
    overlap_frames = profile["overlap_frames"]
    total = profile["total_frames"]

    # v2 新特征
    dir_cons = profile.get("direction_consistency", 0.0)
    dir_stability = profile.get("dominant_direction_stability", 0.0)
    tex_rate = profile.get("texture_change_rate", 0.0)
    baseline = profile.get("baseline_motion", 0.0)

    peak_to_avg_raw = peak_raw / max(avg_raw, 0.001)

    def _fmt_reason(base: str) -> str:
        """格式化 reason，追加关键特征值。"""
        parts = [base]
        parts.append(f"dir_cons={dir_cons:.2f}")
        if tex_rate > 0:
            parts.append(f"tex={tex_rate:.3f}")
        parts.append(f"baseline={baseline:.4f}")
        if adapt_tag:
            parts.append(adapt_tag)
        return ", ".join(parts)

    # ================================================================
    # 1. resting: 几乎无运动 + 方向杂乱
    # ================================================================
    if (avg_raw <= r["resting"]["max_motion"] and motion_ratio < 0.3):
        if dir_cons < r["resting"].get("max_direction_consistency", 0.5):
            # 增强信号: 静止时方向应该很杂乱
            conf = 1.0 - (avg_raw / r["resting"]["max_motion"])
            conf = min(conf + 0.05, 0.95)  # 方向杂乱加分
            return "resting", round(conf, 2), _fmt_reason(
                f"静止: avg={avg_raw:.4f}, motion_ratio={motion_ratio:.2f}, 方向杂乱"
            )

    # ================================================================
    # 2. shedding: 低速长时间运动 + 纹理变化明显 + 方向杂乱
    #    (蜕皮核心特征: 运动弱但纹理在变)
    # ================================================================
    s = r["shedding_candidate"]
    if (s["min_motion"] <= avg_raw <= s["max_motion"] and
            motion_ratio > s["min_sustained_ratio"]):

        shedding_score = 0.0
        flags = []

        # 基本运动条件满足
        shedding_score += 0.3
        flags.append("低速持续")

        # 方向杂乱加分
        if dir_cons < s.get("max_direction_consistency", 0.3):
            shedding_score += 0.15
            flags.append("方向杂乱")
        else:
            shedding_score -= 0.1  # 方向一致更可能是移动

        # 纹理变化加分（核心新增特征）
        min_tex = s.get("min_texture_change_rate", 0.04)
        if tex_rate > min_tex:
            # 纹理变化越大，蜕皮可能性越高
            tex_bonus = min(tex_rate / min_tex * 0.3, 0.35)
            shedding_score += tex_bonus
            flags.append(f"纹理变化({tex_rate:.3f})")
        elif tex_rate < 0.01:
            shedding_score -= 0.15  # 纹理没变化不太可能是蜕皮
            flags.append("纹理无变化(-)")

        shedding_score = max(0.2, min(shedding_score, 0.70))  # v2: 上限提升到 0.70

        if shedding_score >= 0.35:
            return "shedding", round(shedding_score, 2), _fmt_reason(
                f"蜕皮: {', '.join(flags)}"
            )

    # ================================================================
    # 3. feeding_or_strike: 短时间剧烈运动峰值 + 方向高度一致（单向爆发）
    # ================================================================
    fc = r["feeding_or_strike_candidate"]
    if (peak_raw > fc["min_peak_motion"] and
            peak_to_avg_raw > fc["peak_ratio"] and
            peak_ratio < fc["max_peak_duration"]):

        feed_score = 0.0
        flags = []

        # 基本峰值条件
        feed_score += 0.4

        # 方向一致性加分（核心新增：攻击是单向的）
        min_dir = fc.get("min_direction_consistency", 0.55)
        if dir_cons > min_dir:
            dir_bonus = min((dir_cons - min_dir) / (1.0 - min_dir) * 0.35, 0.35)
            feed_score += dir_bonus
            flags.append(f"高方向一致性({dir_cons:.2f})")
        elif dir_cons < 0.3:
            feed_score -= 0.15  # 方向杂乱不太可能是攻击
            flags.append(f"方向杂乱(-)")

        # 主方向稳定性
        if dir_stability > 0.5:
            feed_score += 0.1
            flags.append("主方向稳定")

        feed_score = min(feed_score, 0.92)

        if feed_score >= 0.45:
            return "feeding_or_strike", round(feed_score, 2), _fmt_reason(
                f"攻击/进食: {'; '.join(flags)}, peak={peak_raw:.4f}"
            )

    # ================================================================
    # 4. contact_mating_like: 多运动区域重叠 + 方向杂乱
    # ================================================================
    cm = r["contact_mating_like_candidate"]
    overlap_ratio = overlap_frames / max(total, 1)
    if (max_regions >= cm["min_motion_regions"] and overlap_ratio > 0.2):

        contact_score = 0.0
        flags = []

        # 基本条件
        contact_score += min(overlap_ratio * 0.5, 0.35)

        # 方向杂乱加分（核心新增：交配/接触是多向的）
        max_dir = cm.get("max_direction_consistency", 0.45)
        if dir_cons < max_dir:
            dir_bonus = (max_dir - dir_cons) / max(max_dir, 0.01) * 0.3
            contact_score += dir_bonus
            flags.append(f"方向杂乱({dir_cons:.2f})")
        else:
            contact_score -= 0.1  # 方向太一致，更可能是移动
            flags.append("方向一致(-)")

        contact_score = min(contact_score, 0.85)

        if contact_score >= 0.4:
            return "contact_mating_like", round(contact_score, 2), _fmt_reason(
                f"接触: {'; '.join(flags)}, regions={max_regions}, overlap={overlap_frames}frames"
            )

    # ================================================================
    # 5. moving: 持续中等强度运动 + 方向较稳定
    # ================================================================
    mv = r["moving"]
    if (mv["min_motion"] <= avg_raw <= mv["max_motion"] and
            motion_ratio > mv["min_duration_ratio"]):

        move_score = 0.0
        flags = []

        # 基本条件
        move_score += min(motion_ratio * 0.6, 0.5)

        # 方向稳定性加分
        min_dir = mv.get("min_direction_consistency", 0.25)
        if dir_cons > min_dir:
            # 方向不应太随机
            move_score += min((dir_cons - min_dir) * 0.5, 0.2)
            flags.append(f"方向({dir_cons:.2f})")
        elif dir_cons < 0.15:
            move_score -= 0.1
            flags.append("方向过乱(-)")

        # 排除蜕皮特征（纹理变化大则更可能是蜕皮）
        if tex_rate > 0.06:
            move_score -= 0.15
            flags.append(f"纹理变化大(-)")

        move_score = max(0.3, min(move_score, 0.85))

        if move_score >= 0.35:
            return "moving", round(move_score, 2), _fmt_reason(
                f"移动: {'; '.join(flags)}, avg={avg_raw:.4f}"
            )

    # ================================================================
    # 6. unknown: 不满足以上条件或分数太低
    # ================================================================
    return "unknown", 0.3, _fmt_reason(
        f"不确定: avg={avg_raw:.4f}, peak={peak_raw:.4f}, dir_cons={dir_cons:.2f}"
    )


# ================================================================
# 主流程
# ================================================================

def main():
    parser = argparse.ArgumentParser(description="基于运动+光流+纹理的 Clip 自动标注 (v2)")
    parser.add_argument("--clips-dir", type=str,
                        default=str(PROJECT_ROOT / "data" / "clips" / "usable"),
                        help="Usable clips 目录")
    parser.add_argument("--output", type=str,
                        default=str(PROJECT_ROOT / "data" / "annotations" / "auto_labels.csv"),
                        help="输出 CSV 路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = parser.parse_args()

    config = load_config()
    rules = config["auto_label_rules"]
    label_cn = config["label_cn"]

    clips_dir = Path(args.clips_dir)
    if not clips_dir.exists():
        print(f"错误: 目录不存在: {clips_dir}")
        print("请先运行 screen_clips.py 筛选出 usable clips")
        sys.exit(1)

    clip_files = sorted(clips_dir.glob("*.mp4"))
    if not clip_files:
        clip_files = sorted([p for p in clips_dir.iterdir() if p.suffix == ".mp4"])

    if not clip_files:
        print(f"未找到 clip 文件在: {clips_dir}")
        sys.exit(0)

    flow_params = rules.get("flow_params", {})
    texture_params = rules.get("texture_params", {})

    print(f"待标注: {len(clip_files)} 个 clips")
    print(f"  光流: Farneback (ds={flow_params.get('downsample_ratio', 0.5)})")
    print(f"  纹理: LBP (subsample={texture_params.get('texture_subsample', 4)})")
    print(f"  自适应阈值: {'启用' if rules.get('adaptive', {}).get('enable', True) else '关闭'}")
    print()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "clip_path", "auto_label", "label_cn", "confidence",
            "avg_intensity", "peak_intensity", "motion_frame_ratio",
            "max_regions", "overlap_frames",
            "direction_consistency", "dominant_direction_stability",
            "texture_change_rate", "baseline_motion",
            "norm_avg_intensity", "norm_peak_intensity",
            "reason"
        ])

        stats = {}
        for label in config["labels"].values():
            stats[label] = 0

        for i, clip in enumerate(clip_files):
            print(f"[{i+1}/{len(clip_files)}] {clip.name} ", end="")

            profile = extract_motion_profile(clip, flow_params, texture_params)
            label, confidence, reason = classify_behavior(profile, rules)

            stats[label] = stats.get(label, 0) + 1

            cn = label_cn.get(label, label)
            dir_emoji = ""
            dc = profile.get("direction_consistency", 0)
            if dc > 0.7:
                dir_emoji = "→"
            elif dc > 0.4:
                dir_emoji = "⇉"
            else:
                dir_emoji = "⇶"
            print(f"→ {dir_emoji} {cn} ({confidence:.2f})")

            if args.verbose:
                print(f"    avg={profile['avg_intensity']:.4f}, peak={profile['peak_intensity']:.4f}")
                print(f"    motion_ratio={profile['motion_frame_ratio']:.2f}")
                print(f"    dir_cons={profile.get('direction_consistency', 0):.2f}, "
                      f"tex_change={profile.get('texture_change_rate', 0):.4f}")
                print(f"    baseline={profile.get('baseline_motion', 0):.4f}, "
                      f"norm_avg={profile.get('norm_avg_intensity', 0):.2f}")
                print(f"    reason: {reason}")

            writer.writerow([
                str(clip.resolve()),
                label,
                cn,
                confidence,
                profile["avg_intensity"],
                profile["peak_intensity"],
                profile["motion_frame_ratio"],
                profile["max_regions"],
                profile["overlap_frames"],
                profile.get("direction_consistency", 0),
                profile.get("dominant_direction_stability", 0),
                profile.get("texture_change_rate", 0),
                profile.get("baseline_motion", 0),
                profile.get("norm_avg_intensity", 0),
                profile.get("norm_peak_intensity", 0),
                reason,
            ])

    # 统计摘要
    print(f"\n{'='*50}")
    print(f"  标注统计")
    print(f"{'='*50}")
    for label, count in sorted(stats.items(), key=lambda x: -x[1]):
        if count > 0:
            cn = label_cn.get(label, label)
            bar = "█" * min(count, 40)
            print(f"  {cn:<12} {count:>4}  {bar}")
    print(f"\n结果: {output_path}")


if __name__ == "__main__":
    main()
