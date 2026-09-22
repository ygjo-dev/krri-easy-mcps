import { useEffect } from 'react'
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import CatalogPage from './pages/CatalogPage'
import McpDetailPage from './pages/McpDetailPage'
import ToolboxPage from './pages/ToolboxPage'
import ToolboxProvider from './toolbox/ToolboxProvider'

function ScrollToTop() {
  const { pathname } = useLocation()
  // block body 로 둔다. Chrome 의 window.scrollTo 는 Promise 를 돌려줄 수 있고,
  // 그 값이 effect 의 cleanup 자리로 가면 React 가 함수로 부르다 앱 전체가 죽는다.
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}

export default function App() {
  return (
    <ToolboxProvider>
      <ScrollToTop />
      <header className="site-header">
        <div className="container header-row">
          <Link to="/" className="brand">KRRI EASY MCPs</Link>
          <nav aria-label="주 메뉴">
            <NavLink to="/" end>MCP 탐색</NavLink>
            <NavLink to="/toolbox">도구함</NavLink>
          </nav>
        </div>
      </header>
      <main className="container">
        <Routes>
          <Route path="/" element={<CatalogPage />} />
          <Route path="/mcps/:serverId" element={<McpDetailPage />} />
          <Route path="/toolbox" element={<ToolboxPage />} />
          <Route
            path="*"
            element={
              <div className="state-block">
                <p>페이지를 찾을 수 없습니다.</p>
                <Link to="/" className="pill pill-primary">MCP 탐색</Link>
              </div>
            }
          />
        </Routes>
      </main>
      <footer className="site-footer">
        <div className="container">KRRI EASY MCPs</div>
      </footer>
    </ToolboxProvider>
  )
}
