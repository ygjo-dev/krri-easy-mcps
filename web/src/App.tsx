import { NavLink, Route, Routes } from 'react-router-dom'
import CatalogPage from './pages/CatalogPage'
import McpDetailPage from './pages/McpDetailPage'
import ToolboxPage from './pages/ToolboxPage'
import ToolboxProvider from './toolbox/ToolboxProvider'

export default function App() {
  return (
    <ToolboxProvider>
      <header className="topbar">
        <NavLink to="/" className="brand">KRRI EASY MCPs</NavLink>
        <nav>
          <NavLink to="/" end>MCP 탐색</NavLink>
          <NavLink to="/toolbox">도구함</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<CatalogPage />} />
          <Route path="/mcps/:serverId" element={<McpDetailPage />} />
          <Route path="/toolbox" element={<ToolboxPage />} />
          <Route path="*" element={<p className="muted">페이지를 찾을 수 없습니다.</p>} />
        </Routes>
      </main>
    </ToolboxProvider>
  )
}
