import { Routes, Route, Link, useLocation } from 'react-router-dom'
import UploadPage from './pages/UploadPage'
import VideoDetailPage from './pages/VideoDetailPage'
import ClipsPage from './pages/ClipsPage'
import LocatorPage from './pages/LocatorPage'

export default function App() {
  const location = useLocation()

  return (
    <div className="app">
      <header className="app-header">
        <a href="/" className="logo">🦎 ReptiReplay</a>
        <span className="subtitle">爬宠关键行为自动发现与剪辑</span>
        <nav className="app-nav">
          <Link to="/" className={location.pathname === '/' ? 'nav-active' : ''}>上传</Link>
          <Link to="/clips" className={location.pathname.startsWith('/clips') ? 'nav-active' : ''}>剪辑库</Link>
          <Link to="/locator" className={location.pathname.startsWith('/locator') ? 'nav-active' : ''}>模型检测</Link>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/video/:videoId" element={<VideoDetailPage />} />
          <Route path="/clips" element={<ClipsPage />} />
          <Route path="/locator" element={<LocatorPage />} />
        </Routes>
      </main>
    </div>
  )
}
