/**
 * Main application layout — sidebar + header + content area.
 *
 * Matches the mockup:
 *   - Left sidebar: QA branding, navigation, mini audit log
 *   - Top header: page title, settings, logout
 *   - Main area: page content (rendered via <Outlet />)
 */

import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
  LayoutDashboard,
  FileText,
  ListChecks,
  Upload,
  ClipboardList,
  Settings,
  LogOut,
  Search,
} from 'lucide-react';

const NAV_ITEMS = [
  { to: '/',              icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/matters',       icon: FileText,        label: 'Matters' },
  { to: '/custom-fields', icon: ListChecks,      label: 'Custom Fields' },
  { to: '/bulk-update',   icon: Upload,          label: 'Bulk Operations' },
  { to: '/audit',         icon: ClipboardList,   label: 'Audit Log' },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate('/login');
  }

  return (
    <div className="flex h-screen bg-slate-100">

      {/* ── Sidebar ──────────────────────────────────────────────────── */}
      <aside className="w-64 bg-slate-900 text-white flex flex-col">

        {/* Branding */}
        <div className="px-5 py-6 border-b border-slate-700">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-500 rounded-lg flex items-center justify-center font-bold text-lg">
              QA
            </div>
            <div>
              <div className="font-semibold text-sm">Quill & Arrow</div>
              <div className="text-xs text-slate-400">Clio Data Management</div>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition ${
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Settings at bottom */}
        <div className="px-3 py-4 border-t border-slate-700">
          <NavLink
            to="/settings"
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-slate-400 hover:bg-slate-800 hover:text-white transition"
          >
            <Settings size={18} />
            Settings
          </NavLink>
        </div>
      </aside>

      {/* ── Main content area ────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">

        {/* Top header */}
        <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-6 shrink-0">
          <div className="flex items-center gap-4">
            <div className="relative">
              <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search matters..."
                className="pl-10 pr-4 py-2 bg-slate-100 border-0 rounded-lg text-sm w-72 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div className="flex items-center gap-4">
            <span className="text-sm text-slate-600">
              {user?.full_name || user?.username}
              <span className="ml-2 text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                {user?.role}
              </span>
            </span>
            <button
              onClick={handleLogout}
              className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-red-600 transition"
            >
              <LogOut size={16} />
              Logout
            </button>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
