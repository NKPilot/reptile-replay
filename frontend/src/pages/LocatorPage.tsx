import { useEffect, useMemo, useState } from 'react'
import {
  getLocatorRun,
  listLocatorRuns,
  type LocatorClip,
  type LocatorFrame,
  type LocatorRunDetail,
  type LocatorRunSummary,
} from '../services/api'

export default function LocatorPage() {
  const [runs, setRuns] = useState<LocatorRunSummary[]>([])
  const [selectedRun, setSelectedRun] = useState('')
  const [detail, setDetail] = useState<LocatorRunDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState('')
  const [onlyDetected, setOnlyDetected] = useState(false)
  const [preview, setPreview] = useState<LocatorClip | null>(null)

  useEffect(() => {
    loadRuns()
  }, [])

  useEffect(() => {
    if (selectedRun) loadRun(selectedRun)
  }, [selectedRun])

  async function loadRuns() {
    setLoading(true)
    setError('')
    try {
      const data = await listLocatorRuns()
      setRuns(data.runs)
      if (data.runs.length > 0) setSelectedRun(data.runs[0].run_id)
    } catch {
      setError('加载模型检测记录失败，请检查后端是否运行')
    } finally {
      setLoading(false)
    }
  }

  async function loadRun(runId: string) {
    setDetailLoading(true)
    setError('')
    try {
      setDetail(await getLocatorRun(runId))
    } catch {
      setDetail(null)
      setError('加载模型检测结果失败')
    } finally {
      setDetailLoading(false)
    }
  }

  const clips = useMemo(() => {
    const items = detail?.clips || []
    const filtered = onlyDetected ? items.filter(c => c.has_reptile) : items
    return [...filtered].sort((a, b) => {
      const aConf = a.confidence ?? a.behavior_candidates?.[0]?.confidence ?? 0
      const bConf = b.confidence ?? b.behavior_candidates?.[0]?.confidence ?? 0
      if (bConf !== aConf) return bConf - aConf
      return b.detected_frames - a.detected_frames
    })
  }, [detail, onlyDetected])

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

  function topCandidates(clip: LocatorClip) {
    return (clip.behavior_candidates || []).slice(0, 3)
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
          <img src={frame.preview_url} alt="" loading="lazy" />
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
    return (
      <button
        key={clip.clip_path}
        className={`locator-clip ${clip.has_reptile ? 'locator-hit' : 'locator-miss'}`}
        onClick={() => setPreview(clip)}
      >
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
            {clip.label_cn && (
              <span className="locator-badge locator-badge-behavior">
                {clip.label_cn} {confidenceText(clip.confidence)}
              </span>
            )}
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
      </button>
    )
  }

  return (
    <div className="locator-page">
      <div className="clips-header">
        <h1>模型检测</h1>
        <p className="clips-subtitle">LocateAnything / GroundingDINO 离线剪辑定位结果</p>

        <div className="filter-bar locator-toolbar">
          <select
            value={selectedRun}
            onChange={(e) => setSelectedRun(e.target.value)}
            disabled={runs.length === 0}
          >
            {runs.length === 0 ? (
              <option value="">暂无检测记录</option>
            ) : runs.map(run => (
              <option key={run.run_id} value={run.run_id}>
                {run.filename} · {run.detected_clip_count}/{run.clip_count}
              </option>
            ))}
          </select>
          <button
            className={`btn btn-sm ${onlyDetected ? 'btn-primary' : 'btn-outline'}`}
            onClick={() => setOnlyDetected(v => !v)}
          >
            只看检出
          </button>
          <button className="btn btn-sm btn-outline" onClick={loadRuns}>刷新</button>
        </div>
      </div>

      {loading && <div className="loading"><span className="spinner" /> 加载中...</div>}
      {error && <div className="empty-state"><p>{error}</p></div>}

      {!loading && !error && runs.length === 0 && (
        <div className="empty-state">
          <div className="icon">⌕</div>
          <p>暂无模型检测结果</p>
          <p style={{ fontSize: '0.85rem', marginTop: '8px' }}>
            目标文件：data/results/locateanything_test.json
          </p>
        </div>
      )}

      {detail && !detailLoading && (
        <>
          <div className="locator-summary">
            <div>
              <span>检出率</span>
              <strong>{detail.detected_clip_count}/{detail.clip_count}</strong>
            </div>
            <div>
              <span>抽帧</span>
              <strong>{detail.sample_frames}</strong>
            </div>
            <div>
              <span>耗时</span>
              <strong>{formatSeconds(detail.elapsed_sec)}</strong>
            </div>
            <div>
              <span>后端</span>
              <strong>{detail.backend || '-'}</strong>
            </div>
          </div>

          <div className="locator-run-meta">
            <span>{formatDateTime(detail.created_at)}</span>
            <span>{detail.device || 'unknown'} / {detail.dtype || 'auto'}</span>
            <span title={detail.model_dir}>{detail.model_dir.split('/').pop() || detail.model_dir}</span>
            <span>{detail.prompts.join(', ')}</span>
          </div>

          {clips.length === 0 ? (
            <div className="empty-state"><p>当前过滤条件下没有片段</p></div>
          ) : (
            <div className="locator-grid">
              {clips.map(renderClip)}
            </div>
          )}
        </>
      )}

      {detailLoading && <div className="loading"><span className="spinner" /> 加载检测结果...</div>}

      {preview && (
        <div className="player-overlay" onClick={() => setPreview(null)}>
          <button className="close" onClick={() => setPreview(null)}>×</button>
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
                {preview.label_cn && (
                  <span className="locator-badge locator-badge-behavior">
                    {preview.label_cn} {confidenceText(preview.confidence)}
                  </span>
                )}
                <span className="locator-badge">{preview.detected_frames}/{preview.sampled_frames} 帧</span>
                <span className="locator-badge">{preview.total_detections} 框</span>
              </div>
            </div>
            {renderBehaviorCandidates(preview)}
            {preview.behavior_features && (
              <div className="locator-feature-grid">
                <div><span>连续检出</span><strong>{confidenceText(preview.behavior_features.reptile_continuity)}</strong></div>
                <div><span>ROI 运动</span><strong>{confidenceText(preview.behavior_features.roi_motion_ratio)}</strong></div>
                <div><span>运动峰值</span><strong>{(preview.behavior_features.peak_motion ?? 0).toFixed(3)}</strong></div>
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
    </div>
  )
}
