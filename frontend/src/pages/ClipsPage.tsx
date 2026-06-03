import { useEffect, useMemo, useState } from 'react'
import { listClips, listSources, type ClipItem, type SourceItem } from '../services/api'

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
  const [viewMode, setViewMode] = useState<'list' | 'groups'>('groups')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    setLoading(true)
    setError('')
    try {
      const [clipsData, sourcesData] = await Promise.all([
        listClips({ limit: 300 }),
        listSources(),
      ])
      setClips(clipsData.clips)
      setTotal(clipsData.total)
      setSources(sourcesData.sources)
    } catch {
      setError('加载失败，请检查后端是否运行')
    } finally {
      setLoading(false)
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
            <span className={`type-badge ${LABEL_BADGE_CLASS[clip.auto_label] || 'unknown'}`}>
              {clip.label_cn}
            </span>
          </div>
          <div className="clip-source" title={clip.source_video?.title}>
            📺 {clip.source_video?.title || clip.video_id}
          </div>
          <div className="clip-metrics">
            <span>峰值: {(clip.peak_motion * 100).toFixed(0)}%</span>
            <span>置信: {(clip.confidence * 100).toFixed(0)}%</span>
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
          </div>
        </div>
      </div>

      {loading && (
        <div className="loading"><span className="spinner" /> 加载中...</div>
      )}

      {error && <div className="empty-state"><p>{error}</p></div>}

      {!loading && !error && clips.length === 0 && (
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
                  <tr><td>质量分</td><td>{previewClip.score}/4</td></tr>
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
