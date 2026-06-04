import { useState, useEffect } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import {
  createModelRun,
  getVideo,
  listModelRuns,
  type ModelRunSummary,
  type VideoInfo,
} from '../services/api'

export default function VideoDetailPage() {
  const { videoId } = useParams<{ videoId: string }>()
  const [video, setVideo] = useState<VideoInfo | null>(null)
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
      const runs = await listModelRuns(videoId!).catch(() => ({ runs: [] }))
      setModelRuns(runs.runs)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
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

        <button className="btn btn-primary btn-sm" onClick={handleModelRun} disabled={modelRunning}>
          {modelRunning ? <><span className="spinner" /> 创建中...</> : '重新模型剪辑'}
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

      <div className="empty-state">
        <div className="icon">⌕</div>
        <p>该视频的关键行为剪辑由模型剪辑任务生成。</p>
        <p style={{ fontSize: '0.85rem', marginTop: 8 }}>
          上传页选择视频会自动创建任务；这里可查看历史或重新剪辑。
        </p>
      </div>

      {video.status === 'failed' && (
        <div className="empty-state">
          <div className="icon">❌</div>
          <p>处理失败: {video.error || '未知错误'}</p>
        </div>
      )}
    </div>
  )
}
