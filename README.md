# 🦎 ReptiReplay — 爬宠关键行为自动发现与剪辑

> 自动从长视频中发现疑似爬宠关键行为（进食、蜕皮、交配、移动等），并剪辑出前后片段，方便快速回看。

## 🎯 核心功能

- **📤 视频上传** — 支持上传 mp4 或通过 yt-dlp 从 YouTube/B站 等平台下载
- **✂️ 自动切片** — FFmpeg 将长视频切成 5 秒片段，统一 640p/8fps
- **🔍 行为识别** — OpenCV 运动检测 + 规则引擎，识别 6 类爬宠行为
- **📋 事件聚合** — 滑动窗口推理 + 连续事件合并，生成行为时间线
- **🎬 自动剪辑** — 按事件时间段自动剪出带前后缓冲的视频片段
- **🖥️ Web 预览** — React 前端分组浏览剪辑，支持视频预览和元数据查看
- **✅ 人工复核** — 确认/驳回/修正标签，沉淀训练数据

## 🔖 行为标签

| 标签 | 含义 | 示例 |
|------|------|------|
| `feeding_or_strike` | 进食 / 捕食 | 捕食、扑咬、吞食 |
| `contact_mating_like` | 接触 / 疑似交配 | 两只动物持续接触、缠绕 |
| `shedding` | 疑似蜕皮 | 蜕皮过程或皮屑残留 |
| `moving` | 普通移动 | 正常爬行、走动 |
| `resting` | 静止 / 休息 | 几乎无明显运动 |
| `unknown` | 未知 / 不可用 | 人手、字幕、模糊画面 |

## 🏗️ 技术栈

| 模块 | 技术 |
|------|------|
| 前端 | React 19 + TypeScript + Vite 6 |
| 后端 | FastAPI + Uvicorn |
| 视频处理 | FFmpeg |
| 行为分析 | OpenCV (运动检测 / 帧差分析) |
| 包管理 | uv (Python) + npm (前端) |

## 📁 项目结构

```
reptiReplay/
├── backend/                  # FastAPI 后端
│   └── app/
│       ├── main.py           # 应用入口
│       ├── api/              # 路由层 (videos/events/clips)
│       ├── services/         # 业务层 (运动检测/事件聚合/剪辑器)
│       └── models/           # 数据模型
├── frontend/                 # React 前端
│   └── src/
│       ├── pages/            # 页面组件 (上传/详情/剪辑库)
│       ├── components/       # 公共组件
│       └── services/         # API 调用层
├── scripts/                  # 独立工具脚本
│   ├── download_videos.py    # yt-dlp 批量下载
│   ├── split_video.py        # 视频切片
│   ├── screen_clips.py       # 人工筛选可用片段
│   ├── pipeline.py           # 完整处理流水线
│   ├── detect_humans.py      # 人手检测过滤
│   └── auto_label.py         # 自动标注
├── configs/                  # 配置文件 (labels/rules)
├── data/                     # 数据目录 (clips/events/results)
├── start.sh                  # 一键启动脚本
├── pyproject.toml            # Python 项目配置
└── requirements.txt          # Python 依赖
```

## 🚀 快速开始

### 环境要求

- Python ≥ 3.10
- Node.js ≥ 18
- FFmpeg
- [uv](https://github.com/astral-sh/uv) (Python 包管理)

### 一键启动

```bash
chmod +x start.sh
./start.sh
```

脚本会自动检查/安装依赖，然后同时启动前后端：

- 前端页面：http://localhost:5173
- API 文档：http://localhost:8000/docs

### 手动启动

```bash
# 1. 后端
uv sync
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

# 2. 前端（新终端）
cd frontend
npm install
npm run dev
```

## 🔧 使用流程

### 1. 下载视频

```bash
uv run python scripts/download_videos.py
```

### 2. 切片 & 分析

```bash
uv run python scripts/pipeline.py
```

Pipeline 会自动完成：切片 → 运动检测 → 事件生成 → 剪辑 → 保存结果。

### 3. 人工筛选 (可选)

```bash
uv run python scripts/screen_clips.py
```

交互式筛选工具，逐个判断 clip 是否可用，并为可用片段标注行为标签。

### 4. 浏览结果

打开前端页面 `http://localhost:5173`，进入「剪辑库」查看识别结果：

- **分组视图**：按行为标签分组，可折叠展开
- **列表视图**：平铺浏览所有片段
- 点击任意片段即可播放视频并查看详细元数据

## 📡 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/videos/upload` | 上传视频文件 |
| `POST` | `/api/videos/{id}/process` | 开始分析处理 |
| `GET` | `/api/videos/{id}/events` | 查询事件列表 |
| `POST` | `/api/events/{id}/review` | 人工复核事件 |
| `GET` | `/api/clips/` | 获取剪辑列表 |
| `GET` | `/api/clips/sources` | 获取母视频源 |

## 📊 复核系统

对识别结果进行人工验证，支持四种操作：

- **✅ 确认** — 识别正确
- **❌ 驳回** — 识别错误（误报）
- **🏷️ 标签错误** — 行为类型识别错误，修正标签
- 复核结果自动保存，可用于后续模型训练

## 🔮 后续规划

- [ ] 公开视频数据集增强 (300~500 clips)
- [ ] 训练轻量行为分类模型 (MMAction2 / VideoMAE)
- [ ] 接入真实宠物箱摄像头录像
- [ ] RTSP 实时摄像头 + 环形缓存
- [ ] 自动事件回放 & 推送通知

## 📄 License

MIT License
