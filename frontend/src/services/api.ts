const BASE = '/api'

export interface VideoInfo {
  video_id: string
  filename: string
  original_name: string
  duration: number
  file_size: number
  status: 'uploaded' | 'processing' | 'done' | 'failed'
  created_at: string
  error?: string
}

export interface EventItem {
  event_id: string
  video_id: string
  type: string
  label: string
  label_en: string
  start: number
  end: number
  confidence: number
  clip_path: string
  status: 'pending' | 'confirmed' | 'rejected' | 'wrong_label'
}

export interface EventListResponse {
  video_id: string
  total: number
  events: EventItem[]
}

export async function uploadVideo(file: File): Promise<{ video_id: string }> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE}/videos/upload`, { method: 'POST', body: form })
  if (!res.ok) throw new Error((await res.json()).detail || '上传失败')
  return res.json()
}

export async function listVideos(): Promise<VideoInfo[]> {
  const res = await fetch(`${BASE}/videos/`)
  return res.json()
}

export async function getVideo(videoId: string): Promise<VideoInfo> {
  const res = await fetch(`${BASE}/videos/${videoId}`)
  if (!res.ok) throw new Error('视频不存在')
  return res.json()
}

export async function processVideo(videoId: string): Promise<{ event_count: number }> {
  const res = await fetch(`${BASE}/videos/${videoId}/process`, { method: 'POST' })
  if (!res.ok) throw new Error((await res.json()).detail || '处理失败')
  return res.json()
}

export async function listEvents(videoId: string): Promise<EventListResponse> {
  const res = await fetch(`${BASE}/events/video/${videoId}`)
  return res.json()
}

export async function reviewEvent(eventId: string, status: string, label?: string) {
  const res = await fetch(`${BASE}/events/${eventId}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, label: label || null }),
  })
  return res.json()
}

export function getClipUrl(eventId: string): string {
  return `${BASE}/events/${eventId}/clip`
}

export async function exportAnnotations(videoId: string) {
  const res = await fetch(`${BASE}/events/export/${videoId}`)
  return res.json()
}

// ========== Clips API ==========

export interface ClipItem {
  clip_path: string
  video_id: string
  clip_name: string
  classification: string
  score: number
  avg_blur: number
  avg_motion: number
  peak_motion: number
  reasons: string
  // 人物检测
  has_human: boolean
  // 标注字段
  auto_label: string
  label_cn: string
  confidence: number
  // v2 增强特征
  direction_consistency: number
  dominant_direction_stability: number
  texture_change_rate: number
  baseline_motion: number
  norm_avg_intensity: number
  norm_peak_intensity: number
  source_video: SourceVideo | null
  clip_url: string
}

export interface SourceVideo {
  video_id: string
  title: string
  uploader: string
  duration: number
  webpage_url: string
  thumbnail: string
}

export interface ClipsListResponse {
  total: number
  offset: number
  limit: number
  clips: ClipItem[]
  stats: {
    by_classification: Record<string, number>
    by_label: Record<string, number>
    total_source_videos: number
    total_clips_with_labels: number
  }
}

export interface SourceItem extends SourceVideo {
  usable_clips: number
  unknown_clips: number
  total_clips: number
}

export async function listClips(params?: {
  classification?: string
  label?: string
  video_id?: string
  limit?: number
  offset?: number
}): Promise<ClipsListResponse> {
  const search = new URLSearchParams()
  if (params?.classification) search.set('classification', params.classification)
  if (params?.label) search.set('label', params.label)
  if (params?.video_id) search.set('video_id', params.video_id)
  if (params?.limit) search.set('limit', String(params.limit))
  if (params?.offset) search.set('offset', String(params.offset))
  const qs = search.toString()
  const res = await fetch(`${BASE}/clips/${qs ? '?' + qs : ''}`)
  return res.json()
}

export async function listSources(): Promise<{ sources: SourceItem[] }> {
  const res = await fetch(`${BASE}/clips/sources`)
  return res.json()
}

export async function importSource(sourceVideoId: string): Promise<{
  video_id: string
  source_video_id: string
  status: string
  event_count: number
  message: string
}> {
  const res = await fetch(`${BASE}/videos/import-source/${sourceVideoId}`, { method: 'POST' })
  if (!res.ok) throw new Error((await res.json()).detail || '导入失败')
  return res.json()
}

// ========== History API ==========

export interface HistoryRecord {
  run_id: string
  processed_at: string
  source_video_count: number
  source_titles: string[]
  total_clips: number
  usable_clips: number
  bad_clips: number
  unknown_clips: number
  label_distribution: Record<string, number>
  duration_seconds: number
}

export interface HistoryDetail extends HistoryRecord {
  human_clips: number
  clips: {
    clip_path: string
    video_id: string
    clip_name: string
    classification: string
    score: number
    auto_label: string
    label_cn: string
    confidence: number
    peak_motion: number
    has_human: boolean
  }[]
}

export async function listHistory(): Promise<{ history: HistoryRecord[] }> {
  const res = await fetch(`${BASE}/clips/history`)
  return res.json()
}

export async function getHistoryDetail(runId: string): Promise<HistoryDetail> {
  const res = await fetch(`${BASE}/clips/history/${runId}`)
  return res.json()
}

// ========== Locator API ==========

export interface LocatorRunSummary {
  run_id: string
  filename: string
  created_at: string
  model_dir: string
  backend: string
  device: string
  dtype: string
  prompts: string[]
  sample_frames: number
  elapsed_sec: number
  clip_count: number
  detected_clip_count: number
}

export interface LocatorDetection {
  label?: string
  score?: number | null
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface LocatorFrame {
  frame_index: number
  timestamp_sec: number
  elapsed_sec: number
  preview: string | null
  preview_url: string | null
  detections: LocatorDetection[]
  raw_answer?: string | null
}

export interface LocatorBehaviorCandidate {
  label: string
  label_cn: string
  confidence: number
}

export interface LocatorBehaviorFeatures {
  avg_motion?: number
  peak_motion?: number
  motion_ratio?: number
  roi_motion_ratio?: number
  texture_change?: number
  reptile_continuity?: number
  longest_reptile_segment_ratio?: number
  food_frame_ratio?: number
  shed_frame_ratio?: number
  multi_reptile_frame_ratio?: number
  near_reptile_pair?: boolean
  objects?: string[]
  reptile_segments?: Array<{
    start_frame: number
    end_frame: number
    start_sec: number
    end_sec: number
    length: number
  }>
}

export interface LocatorClip {
  clip_path: string
  clip_url: string | null
  video_meta: {
    total_frames?: number
    fps?: number
    duration_sec?: number
    error?: string
  }
  elapsed_sec: number
  sampled_frames: number
  detected_frames: number
  total_detections: number
  has_reptile: boolean
  labels: string[]
  auto_label?: string
  label_cn?: string
  confidence?: number
  final_label?: string
  final_label_cn?: string
  final_confidence?: number
  final_source?: 'locator' | 'ollama' | string
  review_status?: 'pending' | 'reviewed' | 'skipped' | 'failed' | string
  review_model?: string
  review_error?: string
  llm_label?: string
  llm_label_cn?: string
  llm_confidence?: number
  llm_reason?: string
  llm_has_reptile?: boolean
  candidate_labels?: string[]
  behavior_candidates?: LocatorBehaviorCandidate[]
  behavior_features?: LocatorBehaviorFeatures
  frames: LocatorFrame[]
}

export interface LocatorRunDetail extends LocatorRunSummary {
  clips: LocatorClip[]
}

export async function listLocatorRuns(): Promise<{ runs: LocatorRunSummary[] }> {
  const res = await fetch(`${BASE}/locator/runs`)
  if (!res.ok) throw new Error('加载模型检测记录失败')
  return res.json()
}

export async function getLocatorRun(runId: string): Promise<LocatorRunDetail> {
  const res = await fetch(`${BASE}/locator/runs/${encodeURIComponent(runId)}`)
  if (!res.ok) throw new Error((await res.json()).detail || '加载模型检测结果失败')
  return res.json()
}

// ========== Model Runs API ==========

export interface ModelRunSummary {
  run_id: string
  video_id: string
  source_video_id: string
  source_title: string
  status: 'queued' | 'running' | 'done' | 'failed'
  created_at: string
  started_at: string
  finished_at: string
  error: string
  progress_percent?: number
  progress_stage?: string
  progress_message?: string
  clip_count: number
  visible_clip_count: number
  behavior_distribution: Record<string, number>
  duration_seconds: number
  review_enabled?: boolean
  review_model?: string
  reviewed_clip_count?: number
}

export interface ModelRunDetail extends ModelRunSummary {
  clips: LocatorClip[]
}

export async function createModelRun(params: {
  video_id?: string
  source_video_id?: string
}): Promise<{ run_id: string; video_id: string; source_video_id: string; status: string }> {
  const res = await fetch(`${BASE}/model-runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) throw new Error((await res.json()).detail || '创建模型剪辑任务失败')
  return res.json()
}

export async function listModelRuns(videoId?: string): Promise<{ runs: ModelRunSummary[] }> {
  const qs = videoId ? `?video_id=${encodeURIComponent(videoId)}` : ''
  const res = await fetch(`${BASE}/model-runs${qs}`)
  if (!res.ok) throw new Error('加载模型剪辑历史失败')
  return res.json()
}

export async function getModelRun(runId: string): Promise<ModelRunDetail> {
  const res = await fetch(`${BASE}/model-runs/${encodeURIComponent(runId)}`)
  if (!res.ok) throw new Error((await res.json()).detail || '加载模型剪辑结果失败')
  return res.json()
}

export async function downloadModelRunClips(runId: string, clipPaths: string[]): Promise<Blob> {
  const res = await fetch(`${BASE}/model-runs/${encodeURIComponent(runId)}/download`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clip_paths: clipPaths }),
  })
  if (!res.ok) throw new Error((await res.json()).detail || '下载剪辑失败')
  return res.blob()
}
