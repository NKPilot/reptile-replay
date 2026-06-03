import { useEffect, useMemo, useState } from 'react'
import {
  listClips, listSources, listHistory, getHistoryDetail,
  type ClipItem, type SourceItem, type HistoryRecord,
} from '../services/api'

const LABEL_BADGE_CLASS: Record<string, string> = {
  feeding_or_strike: 'feeding_or_strike',
  contact_mating_like: 'contact_mating_like',
  shedding: 'shedding',
  moving: 'moving',
  resting: 'resting',
  unknown: 'unknown',
}

const LABEL_ORDER = [
  'feeding_or_strike',
  'contact_mating_like',
  'moving',
  'shedding',
  'resting',
  'unknown',
]

const LABEL_EMOJI: Record<string, string> = {
  feeding_or_strike: '🍖',
  contact_mating_like: '💑',
  moving: '🦎',
  shedding: '🐍',
  resting: '😴',
  unknown: '❓',
}

export default function ClipsPage() {
  const [clips, setClips] = useState<ClipItem[]>([])
  const [sources, setSources] = useState<SourceItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [total, setTotal] = useState(0)

  const [previewClip, setPreviewClip] = useState<ClipItem | null>(null)
  const [viewMode, setViewMode] = useState<'list' | 'groups' | 'history'>('groups')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  // 历史记录
  const [historyRecords, setHistoryRecords] = useState<HistoryRecord[]>([])
  const [historyOpenId, setHistoryOpenId] = useState<string | null>(null)
  const [historyClips, setHistoryClips] = useState<ClipItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    setLoading(true)
    setError('')
    try {
      const [clipsData, sourcesData, histData] = await Promise.all([
        listClips({ limit: 300 }),
        listSources(),
        listHistory().catch(() => ({ history: [] })),
      ])
      setClips(clipsData.clips)
      setTotal(clipsData.total)
      setSources(sourcesData.sources)
      setHistoryRecords(histData.history)
    } catch {
      setError('加载失败，请检查后端是否运行')
    } finally {
      setLoading(false)
    }
  }

  async function openHistory(runId: string) {
    if (historyOpenId === runId) {
      setHistoryOpenId(null)
      setHistoryClips([])
      return
    }
    setHistoryOpenId(runId)
    setHistoryLoading(true)
    try {
      const detail = await getHistoryDetail(runId)
      // 将历史 clips 转为标准 ClipItem
      setHistoryClips(detail.clips.map(c => ({
        clip_path: c.clip_path,
        video_id: c.video_id,
        clip_name: c.clip_name,
        classification: c.classification,
        score: c.score,
        avg_blur: 0,
        avg_motion: 0,
        peak_motion: c.peak_motion,
        reasons: '',
        has_human: c.has_human || false,
        auto_label: c.auto_label,
        label_cn: c.label_cn,
        confidence: c.confidence,
        direction_consistency: (c as any).direction_consistency || 0,
        dominant_direction_stability: (c as any).dominant_direction_stability || 0,
        texture_change_rate: (c as any).texture_change_rate || 0,
        baseline_motion: (c as any).baseline_motion || 0,
        norm_avg_intensity: (c as any).norm_avg_intensity || 0,
        norm_peak_intensity: (c as any).norm_peak_intensity || 0,
        source_video: null,
        clip_url: `/static/clips/${c.clip_path}`,
      })))
    } catch {
      setHistoryClips([])
    } finally {
      setHistoryLoading(false)
    }
  }

  // 按标签分组的 clips
  const groups = useMemo(() => {
    const map: Record<string, ClipItem[]> = {}
    for (const c of clips) {
      const key = c.auto_label || 'unknown'
      if (!map[key]) map[key] = []
      map[key].push(c)
    }
    // 按预定义顺序排列
    const ordered: { label: string; labelCn: string; clips: ClipItem[] }[] = []
    for (const key of LABEL_ORDER) {
      if (map[key]?.length) {
        ordered.push({ label: key, labelCn: map[key][0].label_cn, clips: map[key] })
      }
    }
    // 加上不在预定义列表中的
    for (const key of Object.keys(map)) {
      if (!LABEL_ORDER.includes(key)) {
        ordered.push({ label: key, labelCn: map[key][0].label_cn || key, clips: map[key] })
      }
    }
    return ordered
  }, [clips])

  function toggleCollapse(label: string) {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }

  function getClassificationBadge(cls: string) {
    const map: Record<string, { text: string; cls: string }> = {
      usable: { text: '✓ 可用', cls: 'cls-usable' },
      unknown: { text: '? 待定', cls: 'cls-unknown' },
      bad: { text: '✗ 废弃', cls: 'cls-bad' },
    }
    const b = map[cls] || { text: cls, cls: 'cls-unknown' }
    return <span className={`cls-badge ${b.cls}`}>{b.text}</span>
  }

  function formatDuration(sec: number) {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m}:${String(s).padStart(2, '0')}`
  }

  function formatDateTime(iso: string) {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  }

  function renderHistoryCard(rec: HistoryRecord) {
    const isOpen = historyOpenId === rec.run_id
    const labels = Object.entries(rec.label_distribution)
    const maxCount = Math.max(...labels.map(([, c]) => c), 1)

    return (
      <div key={rec.run_id} className="history-card">
        <div className="history-header" onClick={() => openHistory(rec.run_id)}>
          <span className="history-arrow">{isOpen ? '▾' : '▸'}</span>
          <span className="history-icon">📜</span>
          <div className="history-meta">
            <span className="history-date">{formatDateTime(rec.processed_at)}</span>
            <span className="history-videos">
              {rec.source_video_count} 个母视频 → {rec.total_clips} 个片段
            </span>
            <span className="history-duration">{(rec.duration_seconds / 60).toFixed(1)} 分钟</span>
          </div>
          <div className="history-stats">
            <span className="stat-usable">{rec.usable_clips} 可用</span>
            <span className="stat-unknown">{rec.unknown_clips} 待定</span>
            {rec.bad_clips > 0 && <span className="stat-bad">{rec.bad_clips} 废弃</span>}
          </div>
          <div className="history-bars">
            {labels.slice(0, 5).map(([label, count]) => (
              <div key={label} className="history-bar-item" title={`${label}: ${count}`}>
                <div
                  className={`history-bar-fill bar-${label}`}
                  style={{ height: `${(count / maxCount * 100).toFixed(0)}%` }}
                />
                <span className="history-bar-label">{LABEL_EMOJI[label] || '📌'}</span>
              </div>
            ))}
          </div>
        </div>

        {isOpen && (
          <div className="history-clips">
            {rec.source_titles.length > 0 && (
              <div className="history-sources">
                <span className="source-label">母视频：</span>
                {rec.source_titles.map((t, i) => (
                  <span key={i} className="source-tag" title={t}>{t}</span>
                ))}
              </div>
            )}

            {historyLoading && (
              <div className="loading"><span className="spinner" /> 加载片段...</div>
            )}

            {!historyLoading && historyClips.length > 0 && (
              <div className="clips-grid" style={{ padding: '12px 0 0' }}>
                {historyClips.map(renderClipCard)}
              </div>
            )}

            {!historyLoading && historyClips.length === 0 && (
              <p className="history-empty">该记录暂无片段数据</p>
            )}
          </div>
        )}
      </div>
    )
  }

  function renderClipCard(clip: ClipItem) {
    return (
      <div
        key={clip.clip_path}
        className={`clip-card ${clip.classification === 'usable' ? 'clip-usable' : 'clip-unknown'}`}
        onClick={(e) => { e.stopPropagation(); setPreviewClip(clip) }}
      >
        <div className="clip-thumb">
          {clip.source_video?.thumbnail ? (
            <img src={clip.source_video.thumbnail} alt="" loading="lazy"
                 onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
          ) : (
            <span className="no-thumb">🎬</span>
          )}
          <div className="play-icon">▶</div>
        </div>
        <div className="clip-info">
          <div className="clip-name" title={clip.clip_name}>{clip.clip_name}</div>
          <div className="clip-badges">
            {getClassificationBadge(clip.classification)}
            {clip.has_human && <span className="cls-badge cls-human">👤 人物</span>}
            <span className={`type-badge ${LABEL_BADGE_CLASS[clip.auto_label] || 'unknown'}`}>
              {clip.label_cn}
            </span>
          </div>
          <div className="clip-source" title={clip.source_video?.title}>
            📺 {clip.source_video?.title || clip.video_id}
          </div>
          <div className="clip-metrics">
            <span title={`方向一致性: ${(clip.direction_consistency * 100).toFixed(0)}%`}>
              {clip.direction_consistency > 0.55 ? '→→' : clip.direction_consistency > 0.3 ? '⇉' : '⇶'}
            </span>
            <span>峰值: {(clip.peak_motion * 100).toFixed(0)}%</span>
            <span>置信: {(clip.confidence * 100).toFixed(0)}%</span>
            {clip.texture_change_rate > 0.04 && (
              <span title={`纹理变化: ${(clip.texture_change_rate * 100).toFixed(1)}%`}>🔄</span>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="clips-page">
      <div className="clips-header">
        <h1>📋 已识别剪辑片段</h1>
        <p className="clips-subtitle">
          共 {total} 个片段，来自 {sources.length} 个母视频
        </p>

        <div className="filter-bar">
          <span className="source-summary">
            📺 {sources.length} 个母视频 · 🎬 {total} 个片段
          </span>

          <div className="view-toggle">
            <button className={`btn btn-sm ${viewMode === 'groups' ? 'btn-primary' : 'btn-outline'}`}
                    onClick={() => setViewMode('groups')}>📂 分组</button>
            <button className={`btn btn-sm ${viewMode === 'list' ? 'btn-primary' : 'btn-outline'}`}
                    onClick={() => setViewMode('list')}>📋 列表</button>
            <button className={`btn btn-sm ${viewMode === 'history' ? 'btn-primary' : 'btn-outline'}`}
                    onClick={() => setViewMode('history')}>📜 历史</button>
          </div>
        </div>
      </div>

      {loading && (
        <div className="loading"><span className="spinner" /> 加载中...</div>
      )}

      {error && <div className="empty-state"><p>{error}</p></div>}

      {!loading && !error && clips.length === 0 && viewMode !== 'history' && (
        <div className="empty-state">
          <div className="icon">📭</div>
          <p>没有匹配的剪辑片段</p>
        </div>
      )}

      {/* 列表视图 */}
      {!loading && viewMode === 'list' && (
        <div className="clips-grid">
          {clips.map(renderClipCard)}
        </div>
      )}

      {/* 分组视图 */}
      {!loading && viewMode === 'groups' && groups.map((g) => {
        const isOpen = !collapsed.has(g.label)
        return (
          <div key={g.label} className="clip-group">
            <div className="group-header" onClick={() => toggleCollapse(g.label)}>
              <span className="group-arrow">{isOpen ? '▾' : '▸'}</span>
              <span className="group-emoji">{LABEL_EMOJI[g.label] || '📌'}</span>
              <span className="group-label">{g.labelCn}</span>
              <span className="group-count">{g.clips.length} 片段</span>
              <div className="group-bar">
                <div
                  className={`group-bar-fill bar-${g.label}`}
                  style={{ width: `${(g.clips.length / total * 100).toFixed(0)}%` }}
                />
              </div>
            </div>
            {isOpen && (
              <div className="clips-grid">
                {g.clips.map(renderClipCard)}
              </div>
            )}
          </div>
        )
      })}

      {/* 历史视图 */}
      {viewMode === 'history' && !loading && (
        historyRecords.length === 0 ? (
          <div className="empty-state">
            <div className="icon">📭</div>
            <p>暂无剪辑历史记录</p>
            <p style={{ fontSize: '0.85rem', marginTop: '8px' }}>
              运行 pipeline 后将自动保存历史
            </p>
          </div>
        ) : (
          <div className="history-list">
            {historyRecords.map(renderHistoryCard)}
          </div>
        )
      )}

      {/* 预览弹窗 */}
      {previewClip && (
        <div className="player-overlay" onClick={() => setPreviewClip(null)}>
          <button className="close" onClick={() => setPreviewClip(null)}>✕</button>
          <div className="preview-panel" onClick={(e) => e.stopPropagation()}>
            <video src={previewClip.clip_url} controls autoPlay loop
                   style={{ width: '100%', maxHeight: '60vh', borderRadius: '8px', background: '#000' }} />
            <div className="preview-detail">
              <h3>{previewClip.clip_name}</h3>
              <div className="preview-meta">
                <span className={`cls-badge ${previewClip.classification === 'usable' ? 'cls-usable' : 'cls-unknown'}`}>
                  {previewClip.classification}
                </span>
                {previewClip.has_human && <span className="cls-badge cls-human">👤 人物镜头</span>}
                <span className={`type-badge ${LABEL_BADGE_CLASS[previewClip.auto_label] || 'unknown'}`}>
                  {previewClip.label_cn}
                  {previewClip.auto_label !== 'unknown' && (
                    <span style={{ marginLeft: '4px', opacity: 0.7 }}>
                      {(previewClip.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </span>
              </div>
              {previewClip.source_video && (
                <div className="preview-source">
                  <div className="source-title">母视频</div>
                  <a href={previewClip.source_video.webpage_url} target="_blank" rel="noopener">
                    {previewClip.source_video.title}
                  </a>
                  <span>{previewClip.source_video.uploader}</span>
                  <span>{formatDuration(previewClip.source_video.duration)}</span>
                </div>
              )}
              <table className="preview-stats">
                <tbody>
                  <tr><td>平均运动</td><td>{(previewClip.avg_motion * 100).toFixed(1)}%</td></tr>
                  <tr><td>峰值运动</td><td>{(previewClip.peak_motion * 100).toFixed(1)}%</td></tr>
                  <tr><td>模糊度</td><td>{previewClip.avg_blur.toFixed(1)}</td></tr>
                  <tr><td>质量分</td><td>{previewClip.score}/{previewClip.has_human ? 5 : 4}</td></tr>
                  {(previewClip.direction_consistency > 0 || previewClip.texture_change_rate > 0) && (
                    <>
                      <tr className="preview-divider"><td colSpan={2}><hr /></td></tr>
                      <tr><td>方向一致性</td>
                        <td>
                          {(previewClip.direction_consistency * 100).toFixed(0)}%
                          {previewClip.direction_consistency > 0.55 ? ' (单向)' :
                           previewClip.direction_consistency > 0.3 ? ' (较一致)' : ' (杂乱)'}
                        </td>
                      </tr>
                      <tr><td>主方向稳定性</td><td>{(previewClip.dominant_direction_stability * 100).toFixed(0)}%</td></tr>
                      <tr><td>纹理变化率</td>
                        <td>
                          {(previewClip.texture_change_rate * 100).toFixed(2)}%
                          {previewClip.texture_change_rate > 0.04 ? ' ⚠ 纹理变化明显' : ''}
                        </td>
                      </tr>
                      <tr><td>运动基线</td><td>{(previewClip.baseline_motion * 100).toFixed(2)}%</td></tr>
                      {previewClip.norm_avg_intensity > 0 && (
                        <tr><td>归一化强度 (avg)</td><td>{previewClip.norm_avg_intensity.toFixed(1)}x</td></tr>
                      )}
                    </>
                  )}
                  {previewClip.reasons && (
                    <tr><td>备注</td><td>{previewClip.reasons}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
