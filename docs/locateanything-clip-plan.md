# LocateAnything 剪辑筛选计划

## 目标

在剪辑管线里，把 LocateAnything 当作“目标定位层”，而不是最终行为分类器。第一版主要回答这些问题：

- 这个 clip 里是否看得到爬宠？
- 爬宠在画面的什么位置？
- clip 里的运动是否发生在爬宠区域内，而不是背景区域？
- 画面里是否有食物、水盆、人手等上下文对象，让某些行为候选更可信？

第一版目标是提升剪辑质量，减少背景运动、字幕、切镜、人类干扰造成的误报。行为标签先只做候选，等规则、人工复核或后续视频分类模型确认后，再变成最终标签。

## 总体管线

```text
原始视频
  -> 固定长度切片
  -> OpenCV 低成本筛选
  -> 候选 clip
  -> 每个 clip 抽 3-5 帧
  -> LocateAnything 做目标定位
  -> clip 综合评分
  -> 保留 / 降权 / 丢弃 / 人工复核
```

OpenCV 阶段负责“召回”，不要删得太狠。LocateAnything 作为第二轮验证和评分，判断 clip 是否真的围绕爬宠发生了有效内容。

## 阶段 1：固定切片

先用现有切片脚本：

```bash
uv run python scripts/split_video.py --input input.mp4 --width 640 --fps 8 --segment-time 5
```

第一版建议参数：

- clip 长度：5 秒
- FPS：8
- 宽度：640

5 秒更适合捕捉短事件，比如突然移动、转身、捕食瞬间、抬头、探头。更长的行为可以后续通过合并相邻高分 clip 解决。

## 阶段 2：OpenCV 低成本筛选

在跑大模型之前，继续使用现有 OpenCV 特征做第一轮筛选。需要记录这些指标：

- `motion_intensity`：运动像素占比
- `motion_magnitude`：平均帧差幅度
- `num_regions`：独立运动区域数量
- `blur_score`：Laplacian 清晰度分数
- `text_area_ratio`：疑似字幕、水印、文字区域比例
- `scene_cuts`：基于直方图的切镜次数
- `has_human`：当前 Haar/HOG 人物信号

这一阶段只产出候选 clip 和基础指标，不负责最终决策。宁可多留一些 clip 给 LocateAnything 复核，也不要在这里误删。

## 阶段 3：抽帧策略

不要对 clip 的每一帧都跑 LocateAnything。第一版只抽样。

如果 clip 有明显运动峰值，抽这 5 帧：

- 10% 位置
- 35% 位置
- 运动峰值帧
- 运动峰值前 0.5 秒
- 运动峰值后 0.5 秒

如果 clip 没有明显运动峰值，改用均匀抽样：

- 10%
- 30%
- 50%
- 70%
- 90%

如果 V100 吞吐太慢，降到 3 帧：

- 20%
- 运动峰值帧，或者 50%
- 80%

## 阶段 4：定位 Prompt

第一版定位这些对象：

- `reptile`
- `snake`
- `lizard`
- `gecko`
- `turtle`
- `food`
- `water bowl`
- `human hand`

爬宠类 prompt 用来确认目标是否存在，以及目标 bbox。上下文 prompt 用来生成弱行为候选。

第一版不要依赖 `eating snake`、`shedding reptile` 这类行为 prompt。可以作为实验记录，但核心流程应该先定位实体，再结合实体关系和运动特征推断行为候选。

## 阶段 5：clip 综合评分

不要只按模型置信度选 clip。LocateAnything 的不同封装未必有稳定的 per-box confidence，而且模型置信度不一定等于剪辑价值。

建议用综合分：

```text
score =
  目标检出分
+ ROI 运动分
+ 目标连续性分
+ 行为上下文分
- 画质惩罚
- 干扰惩罚
```

第一版权重可以这样设：

- 目标检出分：最多 30 分
- 爬宠 bbox 内运动：最多 25 分
- bbox 连续性和稳定性：最多 15 分
- 行为上下文：最多 20 分
- 画质和干扰惩罚：最多扣 30 分

评分信号示例：

- 抽样帧里检出爬宠的帧越多，分数越高。
- 运动区域和爬宠 bbox 重叠，分数越高。
- 运动主要发生在 bbox 外，应该降权。
- bbox 很小、只在边缘、只出现一帧，应该降权。
- 食物靠近爬宠 bbox，生成 `feeding_candidate`。
- 水盆靠近爬宠 bbox，生成 `drinking_candidate`。
- 人手靠近爬宠 bbox，生成 `interaction_candidate`。
- 模糊、字幕、切镜、明显人物干扰会扣分。

输出示例：

```json
{
  "clip_path": "data/clips/example/clip_00012.mp4",
  "score": 76.5,
  "decision": "keep",
  "has_reptile": true,
  "detected_frames": 4,
  "sampled_frames": 5,
  "roi_motion_ratio": 0.68,
  "candidate_labels": ["locomotion_candidate", "feeding_candidate"],
  "objects": ["snake", "food"],
  "needs_review": false
}
```

## 候选行为标签

第一版只输出候选标签，不输出最终标签：

- `locomotion_candidate`：移动、探索、爬行候选
- `feeding_candidate`：进食候选
- `drinking_candidate`：喝水候选
- `interaction_candidate`：人手或外部互动候选
- `resting_candidate`：静止、休息候选
- `unknown`：无法判断

这些候选标签后续可以进入人工复核、规则调参，也可以作为视频行为分类模型的数据来源。

## 建议新增模块

分阶段新增这些模块：

```text
backend/app/services/reptile_locator.py
```

封装 LocateAnything。输入图片帧和 prompt 列表，输出标准化 bbox 和元数据。

```text
backend/app/services/clip_scorer.py
```

把 OpenCV 指标、定位 bbox、对象关系、画质惩罚合成为 clip 分数和候选标签。

```text
scripts/locate_clips.py
```

离线实验脚本。处理一个 clips 目录，输出 JSON/CSV，不直接影响 Web 主流程。

第一版先保持离线实验，不要直接接进 `video_processor.py`。等速度和输出质量明确后，再决定是否接入正式处理流程。

## V100 测试计划

只在测试 LocateAnything 时启用重依赖组：

```bash
uv sync --group locateanything
```

第一轮实验命令：

```bash
uv run --group locateanything python scripts/locate_clips.py \
  --clips-dir data/clips/usable \
  --limit 20 \
  --sample-frames 5 \
  --output data/results/locateanything_test.json
```

需要记录：

- 单帧推理耗时
- 单个 clip 总耗时
- GPU 峰值显存
- 爬宠检出率
- 误检类型
- 漏检类型
- bbox 是否覆盖真实爬宠运动区域

V100 第一轮使用 FP16。V100 支持 FP16，但不支持 BF16。如果显存或速度不理想，先尝试：

- 输入分辨率降到 512 或 448
- 减少 prompt 数量
- 抽样帧从 5 帧降到 3 帧
- 只对 OpenCV 筛选后的候选 clip 跑 LocateAnything

只有在 FP16 明确跑不动、或者成本不可接受时，再考虑 8-bit / 4-bit 量化。量化可能影响自定义 VLM grounding 行为，也可能降低 bbox 质量。

## MVP 验收标准

第一版满足这些条件就算有价值：

- 大多数可见爬宠 clip 能被识别为有爬宠。
- 明显空镜 clip 能被降权或丢弃。
- 背景运动造成的误报明显减少。
- bbox 内运动和最终保留 clip 有明显相关性。
- 输出 JSON 容易人工复核。
- 单个候选 clip 的处理时间能接受离线批处理。

建议第一轮目标：

- 可见爬宠 clip 检出率：80% 或更高
- 每个 clip 抽样帧数：3-5 帧
- 每帧 prompt 数量：3-8 个
- 第一批测试规模：20 个 clip

## 实施顺序

1. 新增 `scripts/locate_clips.py`，实现抽帧和 JSON 输出。
2. 新增 `backend/app/services/reptile_locator.py`，实现最小模型封装。
3. 在 V100 上跑 20 个 clip，检查输出和速度。
4. 新增 `backend/app/services/clip_scorer.py`，实现简单加权评分。
5. 在 50-100 个 clip 上复测，调整阈值。
6. 增加方便人工复核的 CSV 输出。
7. 决定是否把评分接入主处理流程。

