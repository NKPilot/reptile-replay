import { useState } from 'react'
import { getClipUrl, type EventItem } from '../services/api'

interface Props {
  event: EventItem
  onReview: (eventId: string, status: string, label?: string) => void
}

const STATUS_CN: Record<string, string> = {
  pending: '待复核', confirmed: '已确认', rejected: '已驳回', wrong_label: '标签错误',
}

export default function EventCard({ event, onReview }: Props) {
  const [playing, setPlaying] = useState(false)

  function formatTime(sec: number) {
    const m = Math.floor(sec / 60)
    const s = Math.floor(sec % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  function confClass(val: number) {
    if (val >= 0.7) return 'high'; if (val >= 0.45) return 'mid'; return ''
  }

  return (
    <>
      <div className="event-card">
        <div className="event-thumb">
          {event.clip_path ? (
            <video
              src={getClipUrl(event.event_id)}
              muted preload="metadata"
              onMouseEnter={(e) => (e.target as HTMLVideoElement).play()}
              onMouseLeave={(e) => { (e.target as HTMLVideoElement).pause(); (e.target as HTMLVideoElement).currentTime = 0 }}
              style={{ cursor: 'pointer' }}
              onClick={() => setPlaying(true)}
            />
          ) : (
            <span style={{ color: 'var(--text-dim)', fontSize: '0.8rem' }}>暂无预览</span>
          )}
        </div>

        <div className="event-body">
          <div className={`type-badge ${event.type}`}>{event.label}</div>
          <div className="event-meta">
            <span>⏱ {formatTime(event.start)} ~ {formatTime(event.end)}</span>
            <span>📐 {(event.end - event.start).toFixed(1)}s</span>
          </div>
          <div className={`event-conf ${confClass(event.confidence)}`}>
            置信度: {(event.confidence * 100).toFixed(0)}%
          </div>
          <div style={{ marginTop: 4 }}>
            <span className={`status-badge ${event.status}`}>{STATUS_CN[event.status] || event.status}</span>
          </div>

          {event.status === 'pending' && (
            <div className="event-actions">
              <button className="btn btn-primary btn-sm" onClick={() => onReview(event.event_id, 'confirmed')}>
                ✓ 确认
              </button>
              <button className="btn btn-danger btn-sm" onClick={() => onReview(event.event_id, 'rejected')}>
                ✗ 驳回
              </button>
              <button className="btn btn-warn btn-sm" onClick={() => onReview(event.event_id, 'wrong_label')}>
                ⚡ 标签错误
              </button>
            </div>
          )}
        </div>
      </div>

      {playing && (
        <div className="player-overlay" onClick={() => setPlaying(false)}>
          <button className="close" onClick={() => setPlaying(false)}>×</button>
          <video
            src={getClipUrl(event.event_id)}
            controls autoPlay
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  )
}
