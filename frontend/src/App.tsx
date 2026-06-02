/**
 * Main App component with routing
 */
import { Routes, Route, NavLink } from 'react-router-dom'
import { Rocket, Plus, List } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import NewRelease from './pages/NewRelease'
import ReleaseDetail from './pages/ReleaseDetail'
import Toast from './components/Toast'

export default function App() {
  return (
    <div className="app-container">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <Rocket size={28} />
          <span>Release Ticket</span>
        </div>

        <nav className="sidebar-nav">
          <NavLink
            to="/"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            end
          >
            <List size={20} />
            Dashboard
          </NavLink>

          <NavLink
            to="/new"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            <Plus size={20} />
            New Release
          </NavLink>

          <div className="nav-spacer" />

          <div className="p-4 text-sm text-white/60">
            <p>QueryService</p>
            <p>Deployment Automation</p>
          </div>
        </nav>
      </aside>

      <main className="main-content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<NewRelease />} />
          <Route path="/release/:id" element={<ReleaseDetail />} />
        </Routes>
      </main>

      <Toast />
    </div>
  )
}
