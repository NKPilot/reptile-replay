# 爬宠关键行为识别与自动剪辑 MVP 计划书

## 一、项目背景

爬宠饲养场景中，用户通常需要长时间观察宠物状态，例如蛇、蜥蜴、守宫等爬行动物的：

```text
蜕皮
进食 / 捕食
交配 / 接触
异常活动
长时间静止
```

但这些行为往往发生时间不固定，人工长时间回看录像成本很高。因此可以做一个类似 **NVIDIA 即时回放** 的系统：

> 系统自动从长视频中发现疑似关键行为，并剪辑出前后片段，方便用户快速回看。

---

## 二、项目目标

### MVP 目标

两天内完成一个可演示版本：

```text
上传一段爬宠公开视频
    ↓
系统自动切片分析
    ↓
识别疑似关键行为
    ↓
输出行为发生时间段
    ↓
自动剪辑对应片段
    ↓
页面展示事件列表和视频片段
```

### 第一版定位

第一版不追求生产级精准识别，而是验证：

```text
能不能从长视频中自动发现值得回看的片段
能不能自动剪辑这些片段
能不能形成后续人工复核和数据积累闭环
```

建议产品定位为：

> **爬宠关键行为自动发现与剪辑系统**

而不是：

> 爬宠交配/蜕皮精准识别系统

这样更符合 MVP 阶段的能力边界。

---

## 三、核心应用场景

### 1. 爬宠行为回放

用户上传或接入爬宠视频后，系统自动识别：

```text
疑似进食
疑似蜕皮
疑似交配 / 接触
剧烈活动
普通移动
静止休息
```

并自动剪出对应片段。

---

### 2. 后续摄像头实时监控

MVP 做通后，可以扩展到：

```text
RTSP 摄像头
    ↓
环形缓存最近 1～5 分钟视频
    ↓
实时低帧率识别
    ↓
检测到疑似行为
    ↓
保存触发前后片段
```

最终效果类似：

```text
检测到疑似蜕皮 → 自动保存前 30 秒 + 后 5 分钟视频
检测到疑似捕食 → 自动保存前 10 秒 + 后 30 秒视频
```

---

## 四、总体技术路线

### 阶段一：离线视频 MVP

先不直接做摄像头实时流，而是从公开视频开始。

```text
公开视频自采
    ↓
视频切片
    ↓
人工初筛和标注
    ↓
行为识别 / 规则识别
    ↓
滑动窗口推理
    ↓
事件合并
    ↓
FFmpeg 自动剪辑
    ↓
Web 页面展示
```

### 阶段二：真实摄像头录像适配

```text
真实宠物箱录像
    ↓
离线识别
    ↓
模型/规则调参
    ↓
人工复核
    ↓
积累真实场景数据
```

### 阶段三：实时摄像头识别

```text
RTSP 摄像头
    ↓
FFmpeg 环形缓存
    ↓
低帧率抽帧
    ↓
模型/规则判断
    ↓
事件触发
    ↓
自动保存片段
```

---

## 五、MVP 功能范围

### 两天内必须完成

| 功能            | 是否做           |
| ------------- | ------------- |
| 视频上传          | 做             |
| 视频切片          | 做             |
| OpenCV 简单运动分析 | 做             |
| 疑似行为事件生成      | 做             |
| 事件时间段合并       | 做             |
| FFmpeg 自动剪辑   | 做             |
| 页面展示事件列表      | 做             |
| 片段播放          | 做             |
| 人工确认 / 驳回     | 做，简单版         |
| 数据结果导出        | 可做简单 CSV/JSON |

---

### 两天内暂不做

| 功能             | 原因          |
| -------------- | ----------- |
| 实时摄像头 RTSP     | 工程复杂度较高     |
| 高精度蜕皮识别        | 数据不足        |
| 高精度交配识别        | 容易和接触/打架混淆  |
| 大模型视频理解        | 成本高，延迟高     |
| MMAction2 完整训练 | 两天内容易卡环境和数据 |
| 多用户系统          | MVP 暂无必要    |
| 权限系统           | 暂无必要        |
| 复杂后台管理         | 暂无必要        |

---

## 六、行为标签设计

MVP 第一版建议使用 6 类标签：

```yaml
labels:
  0: resting
  1: moving
  2: feeding_or_strike
  3: shedding
  4: contact_mating_like
  5: unknown
```

### 标签说明

| 标签                    | 中文含义      | 说明             |
| --------------------- | --------- | -------------- |
| `resting`             | 静止 / 休息   | 几乎无明显运动        |
| `moving`              | 普通移动      | 正常爬行、走动        |
| `feeding_or_strike`   | 进食 / 捕食   | 捕食、扑咬、吞食       |
| `shedding`            | 蜕皮        | 蜕皮过程或疑似蜕皮      |
| `contact_mating_like` | 接触 / 疑似交配 | 两只动物持续接触、缠绕、压叠 |
| `unknown`             | 未知 / 不可用  | 人手、字幕、模糊、无关画面  |

第一版建议使用 `contact_mating_like`，不要直接使用 `mating`，因为公开视频中的交配、缠绕、打架、普通接触很容易混淆。

---

## 七、数据采集方案

### 1. 数据来源

MVP 阶段优先使用公开视频自采。

主要来源：

```text
YouTube
B站
公开视频平台
爬宠论坛
Reddit
公开爬宠账号
```

后续可补充：

```text
Animal Kingdom
Roboflow reptile-detection
Kaggle 爬行动物图片数据
真实宠物箱摄像头录像
```

---

### 2. 搜索关键词

#### 蜕皮类

```text
leopard gecko shedding
gecko shedding skin
snake shedding skin
ball python shedding
corn snake shedding
蜥蜴 蜕皮
守宫 蜕皮
蛇 蜕皮
球蟒 蜕皮
玉米蛇 蜕皮
```

#### 进食 / 捕食类

```text
gecko eating cricket
lizard eating insect
bearded dragon feeding
snake strike feeding
snake eating mouse
守宫 吃蟋蟀
蜥蜴 进食
蛇 捕食
```

#### 交配 / 接触类

```text
gecko mating
lizard mating
snake mating
reptiles mating
守宫 交配
蜥蜴 交配
蛇 交配
```

#### 普通移动类

```text
lizard walking
gecko walking
snake crawling
reptile enclosure activity
蜥蜴 爬行
蛇 爬行
守宫 活动
```

#### 静止休息类

```text
gecko resting
snake resting enclosure
lizard basking
守宫 休息
蛇 盘着
蜥蜴 晒背
```

---

### 3. 采集目标

两天 MVP 数据目标：

| 行为                  |  原始视频数量 | 目标可用 clips |
| ------------------- | ------: | ---------: |
| feeding_or_strike   | 20～30 个 |    100～150 |
| shedding            | 10～20 个 |     50～100 |
| contact_mating_like | 10～15 个 |      50～80 |
| moving              | 20～30 个 |    100～150 |
| resting             | 10～20 个 |     80～120 |

总目标：

```text
原始视频：70～100 个
可用 clips：300～500 个
```

---

### 4. 数据管理格式

候选视频元数据建议保存为 CSV：

```csv
source,query,url,title,duration,license,animal,behavior_candidate,status,notes
youtube,"snake shedding skin","...","Ball Python Shedding",420,unknown,snake,shedding,pending,"clear view"
youtube,"gecko eating cricket","...","Leopard Gecko Feeding",180,unknown,gecko,feeding_or_strike,pending,"good close-up"
```

字段建议：

```text
url
platform
title
query
duration
license
uploader
animal_type
behavior_candidate
downloaded
usable
notes
```

---

## 八、数据处理流程

### 1. 下载视频

工具：

```text
yt-dlp
```

示例命令：

```bash
yt-dlp \
  --write-info-json \
  --write-thumbnail \
  --restrict-filenames \
  --download-archive data/downloaded.txt \
  -f "bv*[height<=720]+ba/b[height<=720]" \
  -o "data/raw/%(id)s/%(id)s.%(ext)s" \
  -a urls.txt
```

---

### 2. 视频切片

统一切成 5 秒 clip，降低处理成本。

```bash
ffmpeg -i input.mp4 \
  -vf "scale=640:-2,fps=8" \
  -an \
  -f segment \
  -segment_time 5 \
  -reset_timestamps 1 \
  data/clips/video001_%05d.mp4
```

MVP 推荐统一规格：

```text
分辨率：宽 640
帧率：8 FPS
片段长度：5 秒
音频：去掉
```

---

### 3. 人工筛选

每个 clip 先做可用性筛选：

```text
usable
bad
unknown
```

bad 条件：

```text
没有动物
画面太模糊
全是人手
字幕遮挡严重
镜头切换太快
行为不清楚
重复片段
无关动物或无关内容
```

---

### 4. 人工标注

标注文件：

```csv
clip_path,label,source_video_id,animal_type,behavior_note
clips/usable/abc_00001.mp4,feeding_or_strike,abc,gecko,"eating cricket"
clips/usable/def_00004.mp4,shedding,def,snake,"skin coming off"
```

注意训练集、验证集、测试集要按原视频划分，不能按 clip 随机划分。

错误方式：

```text
同一个原视频切出来的 clips，一部分进 train，一部分进 test
```

正确方式：

```text
video_001 的所有 clips 进入 train
video_002 的所有 clips 进入 val
video_003 的所有 clips 进入 test
```

---

## 九、MVP 识别方案

### 第一版不训练复杂模型

两天内优先使用：

```text
OpenCV 运动检测
帧差分析
简单规则判断
FFmpeg 自动剪辑
人工复核
```

### 识别逻辑

#### 1. 普通移动

```text
当前帧和上一帧差异较大
连续多个窗口存在运动
判定为 moving
```

#### 2. 剧烈动作 / 捕食候选

```text
短时间内运动面积突然增大
局部运动强度明显高于平均水平
判定为 feeding_or_strike_candidate
```

#### 3. 接触 / 疑似交配候选

```text
多个运动区域靠近
多个目标区域重叠
接触状态持续一段时间
判定为 contact_mating_like_candidate
```

#### 4. 蜕皮候选

```text
低速长时间运动
局部浅色区域变化
身体附近出现疑似皮屑/残留物
判定为 shedding_candidate
```

蜕皮第一版误报会较高，建议展示为“疑似蜕皮”。

---

## 十、事件生成与自动剪辑

### 1. 滑动窗口推理

```text
窗口长度：5 秒
步长：2 秒
每个窗口输出一个行为标签和置信度
```

示例：

```text
00:00-00:05 → normal
00:02-00:07 → moving
00:04-00:09 → feeding_or_strike_candidate
00:06-00:11 → feeding_or_strike_candidate
00:08-00:13 → feeding_or_strike_candidate
```

---

### 2. 事件触发规则

```text
同一行为连续 2～3 个窗口置信度 > 0.7
判定为一个事件
```

---

### 3. 事件合并规则

```text
相邻同类事件间隔 < 10 秒
合并为一个事件
```

---

### 4. 剪辑规则

```text
事件开始前 10 秒
事件结束后 20 秒
自动剪辑保存
```

示例：

```text
识别到事件：00:01:20 - 00:01:45
实际剪辑：00:01:10 - 00:02:05
```

---

## 十一、系统架构设计

### MVP 架构

```text
React 前端
   ↓
FastAPI 后端
   ↓
视频上传存储
   ↓
FFmpeg 切片
   ↓
OpenCV 分析
   ↓
事件生成
   ↓
FFmpeg 剪辑
   ↓
事件列表展示
```

---

### 推荐技术栈

| 模块      | 技术                                    |
| ------- | ------------------------------------- |
| 前端      | React + TypeScript                    |
| 后端      | FastAPI                               |
| 视频处理    | FFmpeg                                |
| 抽帧与运动分析 | OpenCV                                |
| 数据存储    | 本地文件 + JSON/CSV                       |
| 任务处理    | FastAPI BackgroundTasks，第一版暂不加 Redis  |
| 后续队列    | Redis                                 |
| 后续模型    | YOLO / MMAction2 / SLEAP / DeepLabCut |
| 后续对象存储  | MinIO                                 |

---

## 十二、后端接口设计

### 1. 上传视频

```http
POST /api/videos/upload
```

功能：

```text
上传 mp4
保存到 data/uploads
生成 video_id
```

---

### 2. 开始处理

```http
POST /api/videos/{video_id}/process
```

功能：

```text
切片
抽帧
行为分析
事件生成
自动剪辑
保存结果
```

---

### 3. 查询事件列表

```http
GET /api/videos/{video_id}/events
```

返回示例：

```json
{
  "video_id": "demo_001",
  "events": [
    {
      "event_id": "evt_001",
      "type": "active_motion",
      "label": "疑似捕食/剧烈活动",
      "start": 82.5,
      "end": 110.0,
      "confidence": 0.78,
      "clip_path": "/events/evt_001.mp4",
      "status": "pending"
    }
  ]
}
```

---

### 4. 人工复核

```http
POST /api/events/{event_id}/review
```

请求示例：

```json
{
  "status": "confirmed",
  "label": "feeding_or_strike"
}
```

状态：

```text
pending
confirmed
rejected
wrong_label
```

---

### 5. 播放剪辑片段

```http
GET /api/events/{event_id}/clip
```

功能：

```text
返回剪辑后的视频片段
```

---

## 十三、推荐项目目录

```text
reptile-action-mvp/
  backend/
    app/
      api/
        videos.py
        events.py
      services/
        video_processor.py
        motion_detector.py
        event_aggregator.py
        clipper.py
        dataset.py
      models/
        video.py
        event.py
      main.py

  frontend/
    src/
      pages/
        UploadPage.tsx
        VideoDetailPage.tsx
      components/
        EventList.tsx
        VideoPlayer.tsx
        EventReviewPanel.tsx

  data/
    uploads/
    raw/
    clips/
    events/
    results/
    annotations/

  scripts/
    download_videos.py
    split_video.py
    make_dataset.py
    infer_video.py
    cut_events.py

  configs/
    labels.yaml
    rules.yaml
```

---

## 十四、两天开发排期

# Day 1：跑通核心闭环

## 上午

目标：完成视频输入和处理基础。

任务：

```text
1. 初始化 FastAPI 项目
2. 初始化 React 页面
3. 实现视频上传接口
4. 保存视频到本地目录
5. 接入 FFmpeg
6. 实现视频切片脚本
```

交付：

```text
用户可以上传 mp4
后端可以把视频切成 5 秒 clips
```

---

## 下午

目标：完成事件识别和剪辑。

任务：

```text
1. OpenCV 抽帧
2. 帧差计算
3. 运动强度计算
4. 生成疑似事件时间段
5. 合并连续事件
6. FFmpeg 自动剪辑事件片段
```

交付：

```text
上传一段视频后
系统可以生成事件 JSON
并自动剪出事件片段
```

---

## 晚上

目标：完成基础页面展示。

任务：

```text
1. 视频详情页
2. 事件列表
3. 片段播放
4. 显示事件类型、时间段、置信度
```

交付：

```text
可以在页面看到识别结果和剪辑片段
```

---

# Day 2：打磨 Demo 和数据闭环

## 上午

目标：优化识别规则。

任务：

```text
1. 调整运动阈值
2. 区分普通移动和剧烈活动
3. 加入事件合并逻辑
4. 加入剪辑前后缓冲时间
5. 支持多类候选标签
```

交付：

```text
事件结果更稳定
误报减少
片段长度更合理
```

---

## 下午

目标：加入人工复核。

任务：

```text
1. 事件确认 / 驳回
2. 修改事件标签
3. 保存复核结果
4. 导出 annotations.csv
```

交付：

```text
用户可以人工确认结果
系统可以沉淀后续训练数据
```

---

## 晚上

目标：准备演示材料。

任务：

```text
1. 准备 3～5 个演示视频
2. 手动筛选效果较好的样例
3. 修复上传、播放、剪辑异常
4. 优化页面观感
5. 准备项目说明
```

交付：

```text
形成可演示 MVP
```

---

## 十五、后续迭代路线

### V0.1：离线视频自动剪辑 MVP

```text
上传视频
自动识别疑似行为
自动剪辑片段
人工复核
```

### V0.2：公开视频数据集增强

```text
采集 300～500 个 clips
人工标注
形成训练集
```

### V0.3：训练轻量行为分类模型

可选方案：

```text
MMAction2
VideoMAE
抽帧图像分类
YOLO + Tracking + XGBoost
```

优先推荐：

```text
先 YOLO / OpenCV / 规则
后 MMAction2
```

---

### V0.4：接入真实宠物箱录像

```text
上传真实摄像头录像
离线识别
人工复核
修正规则和模型
```

---

### V0.5：实时摄像头识别

```text
RTSP 摄像头
FFmpeg 环形缓存
实时低帧率推理
事件触发
自动保存前后片段
```

---

## 十六、风险分析

| 风险           | 影响         | 应对                         |
| ------------ | ---------- | -------------------------- |
| 公开视频质量不稳定    | 模型/规则效果不稳定 | 先人工筛选可用 clips              |
| 蜕皮样本少        | 识别效果差      | 第一版只做疑似蜕皮候选                |
| 交配和接触混淆      | 误判较多       | 标签定义为 contact_mating_like  |
| 大模型成本高       | 不适合低成本 MVP | 第一版不用云端视频大模型               |
| 摄像头实时流复杂     | 两天内风险高     | 先做离线视频                     |
| OpenCV 规则误报多 | 精度有限       | 通过人工复核沉淀数据                 |
| 版权问题         | 商业化受限      | MVP 内部验证，保留来源和 license 元数据 |

---

## 十七、成本评估

### MVP 阶段成本

| 项目    |      成本 |
| ----- | ------: |
| 数据采集  | 主要是人工时间 |
| 视频下载  |      免费 |
| 视频处理  |    本地机器 |
| 模型训练  |  第一版不需要 |
| 存储    |    本地磁盘 |
| 云 API |   不建议使用 |
| GPU   |     非必须 |

### 推荐成本策略

```text
1. 不用云端视频大模型扫全视频
2. 不做高帧率推理
3. 视频统一降到 640 宽、8 FPS
4. 先用 OpenCV 规则
5. 只对疑似片段做后续重模型分析
6. 后续再接本地 GPU 模型
```

---

## 十八、MVP 成功标准

两天 MVP 的成功标准不是高准确率，而是闭环完整。

### 最低成功标准

```text
可以上传视频
可以自动切片
可以生成疑似事件
可以自动剪辑
可以在页面播放剪辑片段
可以人工确认或驳回
```

### 较好成功标准

```text
feeding_or_strike 能明显识别出一部分
moving / resting 能基本区分
contact_mating_like 可以作为候选召回
shedding 可以作为疑似候选
系统可以导出标注数据
```

---

## 十九、最终建议

两天内可以做出一个有展示价值的 MVP，但必须控制范围。

最推荐路线：

```text
公开视频自采
    ↓
FFmpeg 切片
    ↓
OpenCV 运动检测
    ↓
规则生成疑似行为事件
    ↓
FFmpeg 自动剪辑
    ↓
React 页面展示
    ↓
人工复核沉淀数据
```

第一版核心价值：

> **从长视频中自动找出值得回看的爬宠关键行为片段，并剪辑出来。**

后续再逐步升级为：

```text
轻量模型识别
真实摄像头录像识别
实时摄像头环形缓存
自动事件回放
```
