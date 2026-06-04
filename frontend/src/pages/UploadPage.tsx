import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  createModelRun,
  uploadVideo,
  listVideos,
  listSources,
  listModelRuns,
  type ModelRunSummary,
  type VideoInfo,
  type SourceItem,
} from '../services/api'

export default function UploadPage() {
  const [videos, setVideos] = useState<VideoInfo[]>([])
  const [sources, setSources] = useState<SourceItem[]>([])
  const [modelRuns, setModelRuns] = useState<ModelRunSummary[]>([])
  const [uploading, setUploading] = useState(false)
  const [importing, setImporting] = useState<string>('') // 正在导入的素材名
  const [modelSource, setModelSource] = useState('')
  const [modelVideo, setModelVideo] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [dragSource, setDragSource] = useState<string>('') // 拖入的素材 video_id
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    loadVideos()
    loadSources()
    loadModelRuns()
  }, [])

  useEffect(() => {
    if (!modelRuns.some(run => run.status === 'queued' || run.status === 'running')) return
    const timer = window.setInterval(() => {
      loadVideos()
      loadModelRuns()
    }, 3000)
    return () => window.clearInterval(timer)
  }, [modelRuns])

  async function loadVideos() {
    try {
      const list = await listVideos()
      setVideos(list)
    } catch {
      // 后端未启动时静默
    }
  }

  async function loadSources() {
    try {
      const data = await listSources()
      setSources(data.sources)
    } catch {
      // 静默
    }
  }

  async function loadModelRuns() {
    try {
      const data = await listModelRuns()
      setModelRuns(data.runs)
    } catch {
      // 静默
    }
  }

  async function handleFile(file: File) {
    if (!file.name.match(/\.(mp4|mov|avi|mkv|webm)$/i)) {
      setError('请上传 mp4/mov/avi/mkv/webm 格式的视频')
      return
    }
    setError('')
    setUploading(true)
    try {
      const result = await uploadVideo(file)
      await loadVideos()
      const run = await createModelRun({ video_id: result.video_id })
      await loadModelRuns()
      navigate(`/locator?video=${encodeURIComponent(run.video_id)}&run=${encodeURIComponent(run.run_id)}`)
    } catch (e: any) {
      setError(e.message || '上传或模型剪辑失败')
    } finally {
      setUploading(false)
    }
  }

  async function handleImportSource(sourceId: string) {
    const src = sources.find(s => s.video_id === sourceId)
    setError('')
    setImporting(src?.title || sourceId)
    setDragSource('')
    try {
      const run = await createModelRun({ source_video_id: sourceId })
      await loadVideos()
      await loadModelRuns()
      navigate(`/locator?video=${encodeURIComponent(run.video_id)}&run=${encodeURIComponent(run.run_id)}`)
    } catch (e: any) {
      setError(e.message || '素材模型剪辑失败')
    } finally {
      setImporting('')
    }
  }

  async function handleSourceModelRun(sourceId: string) {
    const src = sources.find(s => s.video_id === sourceId)
    setError('')
    setModelSource(sourceId)
    try {
      const run = await createModelRun({ source_video_id: sourceId })
      await loadModelRuns()
      navigate(`/locator?video=${encodeURIComponent(run.video_id)}&run=${encodeURIComponent(run.run_id)}`)
    } catch (e: any) {
      setError(e.message || `创建「${src?.title || sourceId}」模型剪辑任务失败`)
    } finally {
      setModelSource('')
    }
  }

  async function handleUploadedModelRun(videoId: string) {
    setError('')
    setModelVideo(videoId)
    try {
      const run = await createModelRun({ video_id: videoId })
      await loadModelRuns()
      navigate(`/locator?video=${encodeURIComponent(run.video_id)}&run=${encodeURIComponent(run.run_id)}`)
    } catch (e: any) {
      setError(e.message || '创建模型剪辑任务失败')
    } finally {
      setModelVideo('')
    }
  }

  async function handleVideoCardClick(video: VideoInfo) {
    const run = latestRunFor(video.video_id)
    if (run) {
      navigate(`/locator?video=${encodeURIComponent(run.video_id)}&run=${encodeURIComponent(run.run_id)}`)
      return
    }
    await handleUploadedModelRun(video.video_id)
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    setDragSource('')
    // 检查是否是素材拖拽
    const sourceId = e.dataTransfer.getData('application/x-source-video')
    if (sourceId) {
      handleImportSource(sourceId)
      return
    }
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  function formatSize(bytes: number) {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  function latestRunFor(videoId: string) {
    return modelRuns.find(run => run.video_id === videoId)
  }

  function statusClass(video: VideoInfo, run?: ModelRunSummary) {
    if (run?.status === 'queued' || run?.status === 'running') return 'processing'
    if (run?.status === 'done') return 'done'
    if (run?.status === 'failed') return 'failed'
    return video.status
  }

  function statusText(video: VideoInfo, run?: ModelRunSummary) {
    if (run?.status === 'queued') return '排队中'
    if (run?.status === 'running') return '模型剪辑中'
    if (run?.status === 'done') return '已剪辑'
    if (run?.status === 'failed') return '剪辑失败'
    return video.status === 'uploaded' ? '待处理' :
      video.status === 'processing' ? '处理中' :
      video.status === 'done' ? '已完成' :
      video.status === 'failed' ? '失败' : video.status
  }

  function actionText(video: VideoInfo) {
    if (modelVideo === video.video_id) return '创建中...'
    const run = latestRunFor(video.video_id)
    if (run?.status === 'done') return `${run.visible_clip_count}/${run.clip_count} 片段 · 查看结果 →`
    if (run?.status === 'queued' || run?.status === 'running') return '查看进度 →'
    if (run?.status === 'failed') return '查看失败详情 →'
    return '模型剪辑 →'
  }

  return (
    <div className="upload-page">
      <h1>上传爬宠视频</h1>
      <p>支持 mp4 / mov / avi / mkv / webm 格式</p>

      <div
        className={`upload-zone ${dragOver ? 'dragover' : ''} ${dragSource ? 'drag-source' : ''} ${importing ? 'importing' : ''}`}
        onClick={() => fileInput.current?.click()}
        onDragOver={(e) => {
          e.preventDefault(); setDragOver(true)
          // 检测是否拖入了素材
          if (e.dataTransfer.types.includes('application/x-source-video')) {
            setDragSource(e.dataTransfer.getData('application/x-source-video'))
          }
        }}
        onDragLeave={() => { setDragOver(false); setDragSource('') }}
        onDrop={onDrop}
      >
        {importing ? (
          <>
            <div className="spinner" />
            <p style={{ marginTop: 12 }}>正在识别「{importing.slice(0, 30)}」…</p>
            <p className="hint">模型直接识别并剪辑关键行为，请稍候</p>
          </>
        ) : uploading ? (
          <>
            <div className="spinner" />
            <p style={{ marginTop: 12 }}>上传并创建模型剪辑任务...</p>
          </>
        ) : dragSource ? (
          <>
            <div className="icon" style={{ fontSize: '2.5rem' }}>📥</div>
            <p>释放以开始模型剪辑</p>
            <p className="hint" style={{ color: 'var(--accent)' }}>
              {sources.find(s => s.video_id === dragSource)?.title?.slice(0, 40) || dragSource}
            </p>
          </>
        ) : (
          <>
            <div className="icon">📤</div>
            <p>点击或拖拽视频到此处上传</p>
            <p className="hint">选择后会直接开始模型剪辑</p>
          </>
        )}
      </div>

      {error && <p style={{ color: 'var(--danger)', marginBottom: 20 }}>{error}</p>}

      <input
        ref={fileInput} type="file" accept="video/*" style={{ display: 'none' }}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
      />

      {videos.length > 0 && (
        <div className="video-list">
          <h3>已上传的视频 ({videos.length})</h3>
          {videos.map((v) => {
            const run = latestRunFor(v.video_id)
            return (
              <div key={v.video_id} className="video-card"
                   onClick={() => handleVideoCardClick(v)}
                   style={{ cursor: 'pointer' }}>
                <span className="name">{v.original_name}</span>
                <span className="size">{formatSize(v.file_size)}</span>
                <span className={`status ${statusClass(v, run)}`}>
                  {statusText(v, run)}
                </span>
                <span className="video-action">
                  {actionText(v)}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* 素材库 */}
      {sources.length > 0 && (
        <div className="material-library">
          <div className="material-header">
            <h3>📚 素材库（预下载视频）</h3>
            <span className="material-count">{sources.length} 个视频，{sources.reduce((a, s) => a + s.total_clips, 0)} 个已剪辑片段</span>
          </div>
          <div className="material-grid">
            {sources.map((s) => (
              <div
                key={s.video_id}
                className="material-card"
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData('application/x-source-video', s.video_id)
                  e.dataTransfer.effectAllowed = 'move'
                }}
                onDragEnd={() => setDragSource('')}
                onClick={() => handleSourceModelRun(s.video_id)}
              >
                <div className="material-thumb">
                  {s.thumbnail ? (
                    <img src={s.thumbnail} alt="" loading="lazy"
                         onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
                  ) : null}
                  <div className="material-play">▶</div>
                </div>
                <div className="material-body">
                  <div className="material-title" title={s.title}>{s.title}</div>
                  <div className="material-meta">
                    <span>{s.uploader}</span>
                    <span>{Math.floor(s.duration / 60)}:{String(s.duration % 60).padStart(2, '0')}</span>
                  </div>
                  <div className="material-stats">
                    <span className="stat-usable">{s.usable_clips} 可用</span>
                    {s.unknown_clips > 0 && <span className="stat-unknown">{s.unknown_clips} 待定</span>}
                  </div>
                  <div className="material-action">
                    {modelSource === s.video_id ? '创建中...' : '点击开始模型剪辑'}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
