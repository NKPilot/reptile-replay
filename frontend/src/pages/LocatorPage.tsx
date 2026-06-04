import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  downloadModelRunClips,
  getModelRun,
  listModelRuns,
  type LocatorClip,
  type LocatorFrame,
  type ModelRunDetail,
  type ModelRunSummary,
} from '../services/api'

export default function LocatorPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const videoId = searchParams.get('video') || ''
  const requestedRun = searchParams.get('run') || ''
  const [runs, setRuns] = useState<ModelRunSummary[]>([])
  const [selectedRun, setSelectedRun] = useState('')
  const [detail, setDetail] = useState<ModelRunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<LocatorClip | null>(null)
  const [enlargedFrame, setEnlargedFrame] = useState<LocatorFrame | null>(null)
  const [selectedClips, setSelectedClips] = useState<Set<string>>(new Set())
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    loadRuns()
  }, [videoId])

  useEffect(() => {
    if (selectedRun) loadRun(selectedRun)
  }, [selectedRun])

  useEffect(() => {
    if (!detail || !['queued', 'running'].includes(detail.status)) return
    const timer = window.setInterval(() => {
      loadRun(detail.run_id, true)
      loadRuns(true)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [detail?.run_id, detail?.status])

  useEffect(() => {
    setSelectedClips(new Set())
  }, [detail?.run_id])

  async function loadRuns(silent = false) {
    if (!silent) setLoading(true)
    setError('')
    try {
      const data = await listModelRuns(videoId || undefined)
      setRuns(data.runs)
      const ids = new Set(data.runs.map(run => run.run_id))
      const nextRun = (
        requestedRun && ids.has(requestedRun) ? requestedRun :
        selectedRun && ids.has(selectedRun) ? selectedRun :
        data.runs[0]?.run_id || ''
      )
      if (nextRun !== selectedRun) setSelectedRun(nextRun)
      if (!nextRun) setDetail(null)
    } catch {
      setError('加载模型剪辑记录失败，请检查后端是否运行')
    } finally {
      if (!silent) setLoading(false)
    }
  }

  async function loadRun(runId: string, silent = false) {
    if (!silent) setDetailLoading(true)
    setError('')
    try {
      const run = await getModelRun(runId)
      setDetail(run)
      setSearchParams(prev => {
        const next = new URLSearchParams(prev)
        next.set('run', runId)
        if (run.video_id) next.set('video', run.video_id)
        return next
      }, { replace: true })
    } catch {
      setDetail(null)
      setError('加载模型剪辑结果失败')
    } finally {
      if (!silent) setDetailLoading(false)
    }
  }

  const clips = useMemo(() => {
    const items = detail?.clips || []
    return [...items].sort((a, b) => {
      const aConf = displayConfidence(a) ?? a.behavior_candidates?.[0]?.confidence ?? 0
      const bConf = displayConfidence(b) ?? b.behavior_candidates?.[0]?.confidence ?? 0
      if (bConf !== aConf) return bConf - aConf
      return b.detected_frames - a.detected_frames
    })
  }, [detail])

  const selectedClipPaths = useMemo(() => {
    const available = new Set(clips.map(clip => clip.clip_path))
    return Array.from(selectedClips).filter(path => available.has(path))
  }, [clips, selectedClips])

  function formatDateTime(iso: string) {
    if (!iso) return '未知时间'
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return d.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  function formatSeconds(value: number) {
    if (!Number.isFinite(value) || value <= 0) return '-'
    if (value < 60) return `${value.toFixed(1)}s`
    return `${(value / 60).toFixed(1)}min`
  }

  function clipName(clip: LocatorClip) {
    return clip.clip_path.split('/').pop() || clip.clip_path
  }

  function bestPreview(frames: LocatorFrame[]) {
    return frames.find(f => f.preview_url && f.detections.length > 0)?.preview_url
      || frames.find(f => f.preview_url)?.preview_url
      || null
  }

  function confidenceText(value?: number) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '-'
    return `${Math.round(value * 100)}%`
  }

  function displayLabel(clip: LocatorClip) {
    return clip.final_label_cn || clip.label_cn || clip.final_label || clip.auto_label || ''
  }

  function displayConfidence(clip: LocatorClip) {
    return clip.final_confidence ?? clip.confidence
  }

  function reviewText(clip: LocatorClip) {
    if (clip.final_source === 'ollama') return 'Ollama 复核'
    if (clip.review_status === 'failed') return '复核失败'
    if (clip.review_status === 'skipped') return '未复核'
    return ''
  }

  function statusText(status?: string) {
    const map: Record<string, string> = {
      queued: '排队中',
      running: '模型运行中',
      done: '已完成',
      failed: '失败',
    }
    return map[status || ''] || status || '-'
  }

  function progressPercent(run?: ModelRunDetail | ModelRunSummary | null) {
    const value = run?.progress_percent
    if (typeof value === 'number' && Number.isFinite(value)) {
      return Math.max(0, Math.min(100, Math.round(value)))
    }
    if (run?.status === 'done' || run?.status === 'failed') return 100
    return 0
  }

  function closePreview() {
    setPreview(null)
    setEnlargedFrame(null)
  }

  function distributionText(distribution?: Record<string, number>) {
    const entries = Object.entries(distribution || {})
    if (entries.length === 0) return '-'
    return entries.map(([label, count]) => `${label} ${count}`).join(' · ')
  }

  function topCandidates(clip: LocatorClip) {
    return (clip.behavior_candidates || []).slice(0, 3)
  }

  function toggleClip(path: string) {
    setSelectedClips(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  function selectAllClips() {
    setSelectedClips(new Set(clips.map(clip => clip.clip_path)))
  }

  async function handleDownloadSelected() {
    if (!detail || selectedClipPaths.length === 0 || downloading) return
    setDownloading(true)
    setError('')
    try {
      const blob = await downloadModelRunClips(detail.run_id, selectedClipPaths)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${detail.run_id}_clips.zip`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : '下载剪辑失败')
    } finally {
      setDownloading(false)
    }
  }

  function renderBehaviorCandidates(clip: LocatorClip, compact = false) {
    const candidates = topCandidates(clip)
    if (candidates.length === 0) return null
    return (
      <div className={compact ? 'locator-candidates compact' : 'locator-candidates'}>
        {candidates.map((candidate, index) => (
          <span key={`${candidate.label}-${index}`} className={`locator-candidate rank-${index + 1}`}>
            <strong>{candidate.label_cn || candidate.label}</strong>
            <em>{confidenceText(candidate.confidence)}</em>
          </span>
        ))}
      </div>
    )
  }

  function renderFrame(frame: LocatorFrame) {
    return (
      <div key={`${frame.frame_index}-${frame.timestamp_sec}`} className="locator-frame">
        {frame.preview_url ? (
          <button
            type="button"
            className="locator-frame-image"
            onClick={() => setEnlargedFrame(frame)}
            title="查看大图"
          >
            <img src={frame.preview_url} alt="" loading="lazy" />
          </button>
        ) : (
          <div className="locator-frame-empty">无预览</div>
        )}
        <div className="locator-frame-meta">
          <span>{frame.timestamp_sec.toFixed(2)}s</span>
          <span>{frame.detections.length} 框</span>
          <span>{formatSeconds(frame.elapsed_sec)}</span>
        </div>
      </div>
    )
  }

  function renderClip(clip: LocatorClip) {
    const previewUrl = bestPreview(clip.frames)
    const selected = selectedClips.has(clip.clip_path)
    return (
      <div
        key={clip.clip_path}
        className={`locator-clip ${clip.has_reptile ? 'locator-hit' : 'locator-miss'} ${selected ? 'locator-selected' : ''}`}
        role="button"
        tabIndex={0}
        onClick={() => setPreview(clip)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setPreview(clip)
          }
        }}
      >
        <label className="locator-select" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={selected}
            onChange={() => toggleClip(clip.clip_path)}
          />
          <span>选择</span>
        </label>
        <div className="locator-thumb">
          {previewUrl ? (
            <img src={previewUrl} alt="" loading="lazy" />
          ) : clip.clip_url ? (
            <video src={clip.clip_url} muted preload="metadata" />
          ) : (
            <span>无预览</span>
          )}
        </div>
        <div className="locator-clip-body">
          <div className="locator-clip-name" title={clip.clip_path}>{clipName(clip)}</div>
          <div className="locator-badges">
            <span className={`locator-badge ${clip.has_reptile ? 'locator-badge-hit' : 'locator-badge-miss'}`}>
              {clip.has_reptile ? '检出爬宠' : '未检出'}
            </span>
            {displayLabel(clip) && (
              <span className="locator-badge locator-badge-behavior">
                {displayLabel(clip)} {confidenceText(displayConfidence(clip))}
              </span>
            )}
            {reviewText(clip) && <span className="locator-badge">{reviewText(clip)}</span>}
            <span className="locator-badge">{clip.detected_frames}/{clip.sampled_frames} 帧</span>
            <span className="locator-badge">{clip.total_detections} 框</span>
          </div>
          {renderBehaviorCandidates(clip, true)}
          <div className="locator-clip-meta">
            <span>{formatSeconds(clip.elapsed_sec)}</span>
            {clip.video_meta?.duration_sec ? <span>{formatSeconds(clip.video_meta.duration_sec)}</span> : null}
            {clip.labels.length > 0 ? <span>{clip.labels.join(', ')}</span> : null}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="locator-page">
      <div className="clips-header">
        <h1>模型剪辑</h1>
        <p className="clips-subtitle">模型直接识别并剪辑出的关键行为片段</p>

        <div className="filter-bar locator-toolbar">
          <select
            value={selectedRun}
            onChange={(e) => {
              setSelectedRun(e.target.value)
              setSearchParams(prev => {
                const next = new URLSearchParams(prev)
                next.set('run', e.target.value)
                return next
              })
            }}
            disabled={runs.length === 0}
          >
            {runs.length === 0 ? (
              <option value="">暂无模型剪辑记录</option>
            ) : runs.map(run => (
              <option key={run.run_id} value={run.run_id}>
                {formatDateTime(run.created_at)} · {statusText(run.status)} · {run.visible_clip_count}/{run.clip_count}
              </option>
            ))}
          </select>
          <button className="btn btn-sm btn-outline" onClick={() => loadRuns()}>刷新</button>
        </div>
      </div>

      {loading && <div className="loading"><span className="spinner" /> 加载中...</div>}
      {error && <div className="empty-state"><p>{error}</p></div>}

      {!loading && !error && runs.length === 0 && (
        <div className="empty-state">
          <div className="icon">⌕</div>
          <p>暂无模型剪辑结果</p>
          <p style={{ fontSize: '0.85rem', marginTop: '8px' }}>
            请先上传视频，或在素材库中选择一个视频
          </p>
        </div>
      )}

      {detail && !detailLoading && (
        <>
          <div className="locator-summary">
            <div>
              <span>状态</span>
              <strong>{statusText(detail.status)}</strong>
            </div>
            <div>
              <span>关键片段</span>
              <strong>{detail.visible_clip_count}/{detail.clip_count}</strong>
            </div>
            <div>
              <span>耗时</span>
              <strong>{formatSeconds(detail.duration_seconds)}</strong>
            </div>
            <div>
              <span>行为分布</span>
              <strong>{distributionText(detail.behavior_distribution)}</strong>
            </div>
          </div>

          <div className="locator-run-meta">
            <span>{formatDateTime(detail.created_at)}</span>
            <span title={detail.run_id}>{detail.run_id}</span>
            <span title={detail.source_title}>{detail.source_title || detail.video_id}</span>
            {detail.review_enabled ? (
              <span title={detail.review_model}>复核 {detail.reviewed_clip_count || 0} 个</span>
            ) : null}
            {detail.error ? <span>{detail.error}</span> : null}
          </div>

          <div className="locator-progress">
            <div className="locator-progress-head">
              <span>{detail.progress_message || statusText(detail.status)}</span>
              <strong>{progressPercent(detail)}%</strong>
            </div>
            <div className="locator-progress-track" aria-label="模型剪辑进度">
              <div style={{ width: `${progressPercent(detail)}%` }} />
            </div>
          </div>

          {detail.status === 'queued' || detail.status === 'running' ? (
            <div className="loading"><span className="spinner" /> {detail.progress_message || statusText(detail.status)}，结果会自动刷新...</div>
          ) : detail.status === 'failed' ? (
            <div className="empty-state"><p>{detail.error || '模型剪辑失败'}</p></div>
          ) : clips.length === 0 ? (
            <div className="empty-state"><p>没有剪辑出有爬宠且带具体行为的片段</p></div>
          ) : (
            <>
              <div className="locator-bulkbar">
                <span>已选 {selectedClipPaths.length} / {clips.length}</span>
                <button className="btn btn-sm btn-outline" onClick={selectAllClips}>
                  全选当前结果
                </button>
                <button className="btn btn-sm btn-outline" onClick={() => setSelectedClips(new Set())} disabled={selectedClipPaths.length === 0}>
                  清空
                </button>
                <button className="btn btn-sm btn-primary" onClick={handleDownloadSelected} disabled={selectedClipPaths.length === 0 || downloading}>
                  {downloading ? '打包中...' : '批量下载'}
                </button>
              </div>
              <div className="locator-grid">
                {clips.map(renderClip)}
              </div>
            </>
          )}
        </>
      )}

      {detailLoading && <div className="loading"><span className="spinner" /> 加载检测结果...</div>}

      {preview && (
        <div className="player-overlay" onClick={closePreview}>
          <button className="close" onClick={closePreview}>×</button>
          <div className="locator-preview-panel" onClick={(e) => e.stopPropagation()}>
            {preview.clip_url && (
              <video src={preview.clip_url} controls style={{ width: '100%', maxHeight: '42vh', background: '#000' }} />
            )}
            <div className="locator-preview-head">
              <h3>{clipName(preview)}</h3>
              <div className="locator-badges">
                <span className={`locator-badge ${preview.has_reptile ? 'locator-badge-hit' : 'locator-badge-miss'}`}>
                  {preview.has_reptile ? '检出爬宠' : '未检出'}
                </span>
                {displayLabel(preview) && (
                  <span className="locator-badge locator-badge-behavior">
                    {displayLabel(preview)} {confidenceText(displayConfidence(preview))}
                  </span>
                )}
                {reviewText(preview) && <span className="locator-badge">{reviewText(preview)}</span>}
                <span className="locator-badge">{preview.detected_frames}/{preview.sampled_frames} 帧</span>
                <span className="locator-badge">{preview.total_detections} 框</span>
              </div>
            </div>
            {renderBehaviorCandidates(preview)}
            {(preview.llm_reason || preview.review_error) && (
              <div className="locator-review-box">
                <span>{preview.final_source === 'ollama' ? '复核理由' : '复核状态'}</span>
                <strong>{preview.llm_reason || preview.review_error}</strong>
              </div>
            )}
            {preview.behavior_features && (
              <div className="locator-feature-grid">
                <div><span>连续检出</span><strong>{confidenceText(preview.behavior_features.reptile_continuity)}</strong></div>
                <div><span>ROI 运动</span><strong>{confidenceText(preview.behavior_features.roi_motion_ratio)}</strong></div>
                <div><span>运动峰值</span><strong>{(preview.behavior_features.peak_motion ?? 0).toFixed(3)}</strong></div>
                <div><span>蜕皮帧</span><strong>{confidenceText(preview.behavior_features.shed_frame_ratio)}</strong></div>
                <div><span>食物/猎物帧</span><strong>{confidenceText(preview.behavior_features.food_frame_ratio)}</strong></div>
                <div><span>多爬宠帧</span><strong>{confidenceText(preview.behavior_features.multi_reptile_frame_ratio)}</strong></div>
                <div><span>近距离双目标</span><strong>{preview.behavior_features.near_reptile_pair ? '是' : '否'}</strong></div>
                <div><span>对象</span><strong>{preview.behavior_features.objects?.join(', ') || '-'}</strong></div>
              </div>
            )}
            <div className="locator-frame-grid">
              {preview.frames.map(renderFrame)}
            </div>
            {preview.frames.some(f => f.raw_answer) && (
              <details className="locator-raw">
                <summary>Raw answer</summary>
                {preview.frames.filter(f => f.raw_answer).map(f => (
                  <pre key={f.frame_index}>{f.raw_answer}</pre>
                ))}
              </details>
            )}
          </div>
        </div>
      )}

      {enlargedFrame?.preview_url && (
        <div className="frame-lightbox" onClick={() => setEnlargedFrame(null)}>
          <button className="close" onClick={() => setEnlargedFrame(null)}>×</button>
          <figure onClick={(e) => e.stopPropagation()}>
            <img src={enlargedFrame.preview_url} alt="" />
            <figcaption>
              <span>{enlargedFrame.timestamp_sec.toFixed(2)}s</span>
              <span>{enlargedFrame.detections.length} 框</span>
              <span>{formatSeconds(enlargedFrame.elapsed_sec)}</span>
            </figcaption>
          </figure>
        </div>
      )}
    </div>
  )
}
