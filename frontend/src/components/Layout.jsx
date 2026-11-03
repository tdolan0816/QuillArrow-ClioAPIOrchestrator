/**
 * Main application layout — sidebar + header + content area.
 *
 * Matches the mockup:
 *   - Left sidebar: QA branding, navigation, mini audit log
 *   - Top header: page title, settings, logout
 *   - Main area: page content (rendered via <Outlet />)
 *
 * Responsive behaviour (phones / small tablets, below Tailwind `lg` = 1024px):
 *   - The sidebar becomes an off-canvas drawer opened by a hamburger button in
 *     the header, with a backdrop. It closes when a nav link is tapped, on Escape,
 *     or on a backdrop tap.
 *   - The header search box is hidden; the user's name collapses to the role pill.
 *   - Content padding tightens from p-6 to p-4.
 * At `lg` and above every class resolves to the original desktop layout, so the
 * desktop web app renders exactly as before.
 */

import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import {
  LayoutDashboard,
  DollarSign,
  FileText,
  ListChecks,
  Upload,
  FileSymlink,
  ClipboardList,
  Settings,
  LogOut,
  Search,
  Sun,
  Moon,
  Menu,
  X,
} from 'lucide-react';

const NAV_ITEMS = [
  { to: '/',              icon: LayoutDashboard, label: 'Firm-wide Dashboard' },
  { to: '/billing',       icon: DollarSign,      label: 'Billing & Activities' },
  { to: '/matters',       icon: FileText,        label: 'Matters' },
  { to: '/custom-fields', icon: ListChecks,      label: 'Custom Fields' },
  { to: '/bulk-update',   icon: Upload,          label: 'Bulk Operations' },
  { to: '/template-update', icon: FileSymlink,   label: 'Template Mass Update' },
  { to: '/audit',         icon: ClipboardList,   label: 'Audit Log' },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Nav links close the mobile drawer on click (a no-op on desktop, where the
  // drawer state has no visual effect).
  const closeSidebar = () => setSidebarOpen(false);

  // Escape closes the drawer.
  useEffect(() => {
    if (!sidebarOpen) return undefined;
    function onKey(e) {
      if (e.key === 'Escape') setSidebarOpen(false);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sidebarOpen]);

  function handleLogout() {
    logout();
    navigate('/login');
  }

  return (
    <div className="app-shell flex bg-slate-100 dark:bg-slate-900">

      {/* ── Mobile backdrop (below lg only) ─────────────────────────────── */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ── Sidebar ──────────────────────────────────────────────────── */}
      <aside
        id="app-sidebar"
        className={`fixed inset-y-0 left-0 z-40 w-64 bg-slate-900 text-white flex flex-col transform transition-transform duration-200 lg:static lg:translate-x-0 lg:transition-none ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >

        {/* Branding */}
        <div className="px-5 py-6 border-b border-slate-700">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-blue-500 rounded-lg flex items-center justify-center font-bold text-lg">
                QA
              </div>
              <div>
                <div className="font-semibold text-sm">Quill & Arrow</div>
                <div className="text-xs text-slate-400">Clio Data Management</div>
              </div>
            </div>
            {/* Close button — mobile drawer only */}
            <button
              type="button"
              onClick={() => setSidebarOpen(false)}
              aria-label="Close menu"
              className="lg:hidden p-2 -mr-2 rounded-lg text-slate-300 hover:bg-slate-800 hover:text-white transition"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              onClick={closeSidebar}
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
            onClick={closeSidebar}
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-slate-400 hover:bg-slate-800 hover:text-white transition"
          >
            <Settings size={18} />
            Settings
          </NavLink>
        </div>
      </aside>

      {/* ── Main content area ────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">

        {/* Top header */}
        <header className="h-16 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between px-4 lg:px-6 shrink-0">
          <div className="flex items-center gap-4">
            {/* Hamburger — mobile only */}
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open menu"
              aria-controls="app-sidebar"
              aria-expanded={sidebarOpen}
              className="lg:hidden p-2 -ml-2 rounded-lg text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700 transition"
            >
              <Menu size={20} />
            </button>
            <div className="relative hidden lg:block">
              <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search..."
                className="pl-10 pr-4 py-2 bg-slate-100 dark:bg-slate-700 dark:text-slate-100 dark:placeholder-slate-400 border-0 rounded-lg text-sm w-72 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div className="flex items-center gap-3 lg:gap-4">
            {/* Dark Mode toggle — applies instantly app-wide via ThemeContext */}
            <button
              onClick={toggleTheme}
              aria-label={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
              title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
              className="p-2 rounded-lg text-slate-500 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-700 transition"
            >
              {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <span className="text-sm text-slate-600 dark:text-slate-300 flex items-center">
              <span className="hidden sm:inline">{user?.full_name || user?.username}</span>
              <span className="sm:ml-2 text-xs bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200 px-2 py-0.5 rounded-full">
                {user?.role}
              </span>
            </span>
            <button
              onClick={handleLogout}
              aria-label="Logout"
              title="Logout"
              className="flex items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400 hover:text-red-600 dark:hover:text-red-400 transition"
            >
              <LogOut size={16} />
              <span className="hidden sm:inline">Logout</span>
            </button>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
