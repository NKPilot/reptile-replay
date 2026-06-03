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
