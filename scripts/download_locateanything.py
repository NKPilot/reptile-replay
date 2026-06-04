#!/usr/bin/env python3
"""
LocateAnything-3B 模型下载脚本 —— 从 ModelScope 下载 NVIDIA 视觉定位模型。

模型信息:
    名称: LocateAnything-3B
    来源: ModelScope (nv-community)
    架构: Eagle VLM + Parallel Box Decoding (PBD)
    能力: 开放词汇物体检测 | 指代表达定位 | OCR/GUI 定位
    输入: 图片/视频 + 文字描述 (如 "reptile", "snake", "lizard")
    输出: 目标边界框 (bounding boxes)
    显存: 约 16GB (consumer GPU 可跑)
    大小: ~6GB (fp16)

在本项目中的用途:
    → 用文字 prompt 定位爬宠在画面中的位置
    → 过滤无人/无宠物的无效片段
    → 结合运动检测，只在爬宠区域分析运动，降低误报
    → 区分不同爬宠个体（如多条蛇）

依赖 (独立安装，不进入项目主依赖):
    pip install modelscope

用法:
    # 预览
    python download_locateanything.py --dry-run

    # 下载模型
    python download_locateanything.py

    # 指定保存目录
    python download_locateanything.py --models-dir /path/to/models
"""

import argparse
import importlib
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODELS_DIR = PROJECT_ROOT / "models"

MODEL_REPO = "nv-community/LocateAnything-3B"
MODEL_NAME = "locateanything-3b"
MODEL_SIZE_ESTIMATE = "~6GB (fp16)"


def check_modelscope() -> bool:
    """检查 modelscope SDK 是否可用。"""
    if importlib.util.find_spec("modelscope") is None:
        print("❌ 需要 modelscope SDK")
        print("   请运行: pip install modelscope")
        return False
    return True


def download(models_dir: Path, force: bool = False) -> bool:
    """从 ModelScope 下载 LocateAnything-3B。"""
    modelscope = importlib.import_module("modelscope")
    snapshot_download = modelscope.snapshot_download

    save_dir = models_dir / MODEL_NAME

    # 已下载检查
    if save_dir.exists() and any(save_dir.iterdir()) and not force:
        model_files = (
            list(save_dir.glob("*.bin"))
            + list(save_dir.glob("*.safetensors"))
            + list(save_dir.glob("*.pt"))
            + list(save_dir.glob("*.json"))
        )
        if model_files:
            total_size = sum(
                f.stat().st_size for f in save_dir.rglob("*") if f.is_file()
            )
            size_mb = total_size / (1024 * 1024)
            print(f"✅ 已存在 ({size_mb:.0f}MB)，跳过。使用 --force 强制重新下载。")
            return True

    save_dir.mkdir(parents=True, exist_ok=True)

    print(f"📥 ModelScope: {MODEL_REPO}")
    print(f"📁 保存到: {save_dir}")
    print(f"📏 预计大小: {MODEL_SIZE_ESTIMATE}")
    print()

    try:
        snapshot_download(
            MODEL_REPO,
            local_dir=str(save_dir),
        )
        print(f"\n✅ 下载完成: {save_dir}")
        return True
    except Exception as e:
        print(f"\n❌ 下载失败: {e}")
        print("提示: 可以重试运行，modelscope SDK 支持断点续传。")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="下载 LocateAnything-3B 视觉定位模型 (ModelScope)"
    )
    parser.add_argument(
        "--models-dir", type=str,
        default=str(DEFAULT_MODELS_DIR),
        help=f"模型保存目录 (默认: {DEFAULT_MODELS_DIR})",
    )
    parser.add_argument(
        "--force", "-f", action="store_true",
        help="强制重新下载",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅预览，不下载",
    )
    args = parser.parse_args()

    models_dir = Path(args.models_dir)

    print(f"\n{'='*60}")
    print("  LocateAnything-3B 模型下载")
    print(f"{'='*60}")
    print(f"  来源: ModelScope ({MODEL_REPO})")
    print(f"  目录: {models_dir / MODEL_NAME}")
    print(f"  大小: {MODEL_SIZE_ESTIMATE}")
    if args.dry_run:
        print("  模式: 预览 (--dry-run)")
    print()

    if args.dry_run:
        print("运行 `python download_locateanything.py` 开始下载。")
        return

    if not check_modelscope():
        sys.exit(1)

    ok = download(models_dir, args.force)

    if ok:
        model_path = models_dir / MODEL_NAME
        print(f"\n{'='*60}")
        print(f"  模型就绪: {model_path}")
        print()
        print("  下一步 —— 在 clipping pipeline 中的使用方式:")
        print("  ──────────────────────────────────────────────")
        print("  见 scripts/ 目录下后续的 reptile_locate.py")
        print("  核心思路:")
        print("    ┌─ pipeline ───────────────────────────┐")
        print("    │ 1. 视频切片 (split_video)              │")
        print("    │ 2. 爬宠定位 (LocateAnything)  ← new    │")
        print("    │    抽样帧 → prompt='reptile' → bbox    │")
        print("    │    过滤: 无爬宠帧占比>80% → 丢弃clip   │")
        print("    │ 3. 运动检测 (motion detector)          │")
        print("    │    仅在爬宠 bbox 区域内分析运动         │")
        print("    │ 4. 行为分类 (auto_label)               │")
        print("    │ 5. 剪辑输出                            │")
        print("    └───────────────────────────────────────┘")
        print("  ──────────────────────────────────────────────")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
