import { useState, useEffect } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import {
  createModelRun,
  getVideo,
  listEvents,
  listModelRuns,
  processVideo,
  reviewEvent,
  exportAnnotations,
  type EventItem,
  type ModelRunSummary,
  type VideoInfo,
} from '../services/api'
import EventCard from '../components/EventCard'

export default function VideoDetailPage() {
  const { videoId } = useParams<{ videoId: string }>()
  const [video, setVideo] = useState<VideoInfo | null>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [processing, setProcessing] = useState(false)
  const [modelRunning, setModelRunning] = useState(false)
  const [modelRuns, setModelRuns] = useState<ModelRunSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    if (!videoId) return
    loadVideo()
  }, [videoId])

  async function loadVideo() {
    try {
      const v = await getVideo(videoId!)
      setVideo(v)
      if (v.status === 'done') {
        const evts = await listEvents(videoId!)
        setEvents(evts.events)
      }
      const runs = await listModelRuns(videoId!).catch(() => ({ runs: [] }))
      setModelRuns(runs.runs)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleProcess() {
    if (!videoId) return
    setProcessing(true)
    setError('')
    try {
      await processVideo(videoId)
      // 刷新状态
      const v = await getVideo(videoId)
      setVideo(v)
      const evts = await listEvents(videoId)
      setEvents(evts.events)
    } catch (e: any) {
      setError(e.message || '处理失败')
    } finally {
      setProcessing(false)
    }
  }

  async function handleModelRun() {
    if (!videoId) return
    setModelRunning(true)
    setError('')
    try {
      const run = await createModelRun({ video_id: videoId })
      navigate(`/locator?video=${encodeURIComponent(run.video_id)}&run=${encodeURIComponent(run.run_id)}`)
    } catch (e: any) {
      setError(e.message || '创建模型剪辑任务失败')
    } finally {
      setModelRunning(false)
    }
  }

  async function handleReview(eventId: string, status: string, label?: string) {
    await reviewEvent(eventId, status, label)
    setEvents((prev) =>
      prev.map((e) =>
        e.event_id === eventId
          ? { ...e, status: status as EventItem['status'], ...(label ? { type: label } : {}) }
          : e
      )
    )
  }

  async function handleExport() {
    if (!videoId) return
    const data = await exportAnnotations(videoId)
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = `annotations_${videoId}.json`; a.click()
    URL.revokeObjectURL(url)
  }

  if (loading) return <div className="loading"><span className="spinner" /> 加载中...</div>
  if (error) return <div className="empty-state"><div className="icon">⚠️</div><p>{error}</p><Link to="/" className="btn btn-outline" style={{marginTop:16}}>返回首页</Link></div>
  if (!video) return null

  return (
    <div className="video-detail">
      <Link to="/" className="back-link">← 返回列表</Link>

      <div className="video-info-bar">
        <h2>{video.original_name}</h2>
        <span className={`status ${video.status}`}>
          {video.status === 'uploaded' ? '待处理' :
           video.status === 'processing' ? '处理中...' :
           video.status === 'done' ? '已完成' :
           video.status === 'failed' ? '失败' : video.status}
        </span>

        {video.status === 'uploaded' && (
          <button className="btn btn-primary" onClick={handleProcess} disabled={processing}>
            {processing ? <><span className="spinner" /> 分析中...</> : '⚡ 开始分析'}
          </button>
        )}

        {video.status === 'done' && events.length > 0 && (
          <button className="btn btn-outline btn-sm" onClick={handleExport}>📥 导出标注</button>
        )}

        <button className="btn btn-primary btn-sm" onClick={handleModelRun} disabled={modelRunning}>
          {modelRunning ? <><span className="spinner" /> 创建中...</> : '开始模型剪辑'}
        </button>
      </div>

      {modelRuns.length > 0 && (
        <div className="locator-run-meta" style={{ marginBottom: 18 }}>
          <span>模型剪辑历史</span>
          {modelRuns.slice(0, 4).map(run => (
            <button
              key={run.run_id}
              className="btn btn-sm btn-outline"
              onClick={() => navigate(`/locator?video=${encodeURIComponent(run.video_id)}&run=${encodeURIComponent(run.run_id)}`)}
            >
              {run.status === 'done' ? `${run.visible_clip_count}/${run.clip_count}` : run.status}
            </button>
          ))}
        </div>
      )}

      {video.status === 'done' && (
        <div className="events-section">
          <h3>疑似关键行为 <span className="event-count">({events.length} 个事件)</span></h3>

          {events.length === 0 ? (
            <div className="empty-state">
              <div className="icon">🔍</div>
              <p>未检测到明显的关键行为</p>
            </div>
          ) : (
            events.map((evt) => (
              <EventCard key={evt.event_id} event={evt} onReview={handleReview} />
            ))
          )}
        </div>
      )}

      {video.status === 'failed' && (
        <div className="empty-state">
          <div className="icon">❌</div>
          <p>处理失败: {video.error || '未知错误'}</p>
        </div>
      )}
    </div>
  )
}
