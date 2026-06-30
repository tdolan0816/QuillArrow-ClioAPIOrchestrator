/**
 * Billing & Activities Dashboard
 *
 * Shows firm activity data from Clio (Time + Expense entries) with:
 *   - KPI cards (total billed, hours, entries)
 *   - Monthly bar chart (Chart.js stacked bar with tooltips)
 *   - Breakdown by attorney
 *   - Data table with filters
 */

import { useState, useEffect, useRef } from 'react';
import { get, post } from '../api/client';
import {
  DollarSign,
  Clock,
  FileText,
  RefreshCw,
  Loader2,
  TrendingUp,
  Filter,
  ChevronDown,
  ChevronUp,
  Users,
} from 'lucide-react';
// Chart.js with auto-registration of all components.
// We use the canvas API directly (not react-chartjs-2) for React 19 compatibility.
import Chart from 'chart.js/auto';

const BAR_COLORS = ['#3b82f6', '#10b981'];
const PIE_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#f97316', '#84cc16', '#ec4899', '#6366f1',
];

function KpiCard({ icon: Icon, label, value, subtitle, color, loading }) {
  return (
    <div className="bg-white rounded-xl p-5 shadow-sm border border-slate-200">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium text-slate-500">{label}</span>
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${color}`}>
          <Icon size={18} className="text-white" />
        </div>
      </div>
      <div className="text-2xl font-bold text-slate-800">
        {loading ? '...' : value}
      </div>
      {subtitle && <p className="text-xs text-slate-400 mt-1">{subtitle}</p>}
    </div>
  );
}

function formatCurrency(val) {
  if (val == null) return '$0';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(val);
}

function formatHours(val) {
  if (val == null) return '0h';
  return `${Number(val).toFixed(1)}h`;
}

// Default to month-to-date when the dashboard first loads — executives almost
// always want "what's happened this month so far" rather than all-time data.
function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function firstOfMonthISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
}

// Format a period key from the backend into a short display label.
//   month "2026-06"      -> "Jun '26"
//   week  "2026-25"      -> "Wk 25"
//   day   "2026-06-23"   -> "Jun 23"
function formatPeriodLabel(period, granularity) {
  if (!period) return '';
  if (granularity === 'day') {
    const [y, m, d] = period.split('-').map(Number);
    if (!y || !m || !d) return period;
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }
  if (granularity === 'week') {
    const parts = period.split('-');
    const week = parts[parts.length - 1];
    return `Wk ${parseInt(week, 10)}`;
  }
  // month
  const [y, m] = period.split('-').map(Number);
  if (!y || !m) return period;
  const dt = new Date(y, m - 1, 1);
  return dt.toLocaleDateString('en-US', { month: 'short' }) + ` '${String(y).slice(-2)}`;
}

const GRANULARITY_LABELS = {
  day: { title: 'Daily Activity Totals', subtitle: 'Last 30 Days' },
  week: { title: 'Weekly Activity Totals', subtitle: 'Last 12 Weeks' },
  month: { title: 'Monthly Activity Totals', subtitle: 'Last 6 Months' },
};

// Chart.js stacked bar chart with tooltips and axis labels.
// Uses Chart.js directly via useRef/useEffect to avoid React 19 incompatibilities
// in third-party wrappers (we hit similar issues with recharts and react-chartjs-2).
function MonthlyBarChart({ data, granularity }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current) return;
    if (!data || data.length === 0) return;

    // Destroy any prior chart bound to this canvas before creating a new one.
    if (chartRef.current) {
      chartRef.current.destroy();
      chartRef.current = null;
    }

    // Period field comes back from the backend as `period` (granularity-agnostic).
    // Fall back to `month` for backward compat with any cached responses.
    const getPeriod = d => d.period ?? d.month;

    chartRef.current = new Chart(canvasRef.current, {
      type: 'bar',
      data: {
        labels: data.map(d => formatPeriodLabel(getPeriod(d), granularity)),
        datasets: [
          {
            label: 'Time',
            data: data.map(d => d.time_total || 0),
            backgroundColor: BAR_COLORS[0],
            borderRadius: 0,
            borderSkipped: false,
          },
          {
            label: 'Expenses',
            data: data.map(d => d.expense_total || 0),
            backgroundColor: BAR_COLORS[1],
            borderRadius: 0,
            borderSkipped: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            stacked: true,
            grid: { display: false },
            ticks: { font: { size: 11 }, color: '#64748b' },
          },
          y: {
            stacked: true,
            beginAtZero: true,
            grid: { color: '#f1f5f9' },
            ticks: {
              font: { size: 11 },
              color: '#64748b',
              callback: function (value) {
                return '$' + Number(value).toLocaleString('en-US', { maximumFractionDigits: 0 });
              },
            },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#1e293b',
            titleColor: '#f8fafc',
            bodyColor: '#f8fafc',
            padding: 12,
            cornerRadius: 8,
            displayColors: true,
            callbacks: {
              label: function (context) {
                const label = context.dataset.label || '';
                const value = context.parsed.y;
                return label + ': ' + formatCurrency(value);
              },
              footer: function (tooltipItems) {
                let total = 0;
                tooltipItems.forEach(item => { total += item.parsed.y; });
                return 'Total: ' + formatCurrency(total);
              },
            },
          },
        },
        interaction: { mode: 'index', intersect: false },
      },
    });

    return () => {
      if (chartRef.current) {
        chartRef.current.destroy();
        chartRef.current = null;
      }
    };
  }, [data, granularity]);

  if (!data || data.length === 0) {
    return <p className="text-sm text-slate-400 text-center py-12">No Data Found for Selected Period</p>;
  }

  return (
    <div className="h-56">
      <canvas ref={canvasRef} />
    </div>
  );
}

// Compact category list used inside the split "Top Categories" cards.
// Renders a horizontal bar per category, sized relative to the top entry.
function CategoryList({ data, emptyMessage = 'No data for this period' }) {
  if (!data || data.length === 0) {
    return <p className="text-sm text-slate-400 text-center py-6">{emptyMessage}</p>;
  }
  const maxTotal = data[0]?.total || 1;
  return (
    <div className="space-y-2.5">
      {data.map((cat, i) => {
        const pct = Math.max((cat.total / maxTotal) * 100, 2);
        return (
          <div key={cat.category + i} className="flex items-center gap-3">
            <span className="w-32 text-xs text-slate-600 truncate" title={cat.category}>
              {cat.category}
            </span>
            <div className="flex-1 bg-slate-100 rounded-full h-2">
              <div
                className="h-2 rounded-full transition-all"
                style={{ width: `${pct}%`, backgroundColor: PIE_COLORS[i % PIE_COLORS.length] }}
              />
            </div>
            <span className="text-xs text-slate-500 w-20 text-right">{formatCurrency(cat.total)}</span>
          </div>
        );
      })}
    </div>
  );
}

// Horizontal bar list for attorney breakdown
function AttorneyBreakdown({ data }) {
  if (!data || data.length === 0) {
    return <p className="text-sm text-slate-400 text-center py-8">No Data Found</p>;
  }

  const maxTotal = data[0]?.total || 1;

  return (
    <div className="space-y-2.5">
      {data.slice(0, 8).map((u, i) => {
        const pct = Math.max((u.total / maxTotal) * 100, 2);
        return (
          <div key={u.user_name || i}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-slate-700 truncate max-w-[140px]">{u.user_name || 'Unknown'}</span>
              <span className="text-xs text-slate-500">{formatCurrency(u.total)} · {formatHours(u.hours)}</span>
            </div>
            <div className="w-full bg-slate-100 rounded-full h-2">
              <div className="h-2 rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: PIE_COLORS[i % PIE_COLORS.length] }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function BillingDashboardPage() {
  const [summary, setSummary] = useState(null);
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState('');
  const [error, setError] = useState(null);

  // Filters — default to month-to-date so the landing view answers the
  // exec-friendly question "what's happened this month so far?"
  const [dateFrom, setDateFrom] = useState(firstOfMonthISO);
  const [dateTo, setDateTo] = useState(todayISO);
  const [typeFilter, setTypeFilter] = useState('');
  const [userFilter, setUserFilter] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [showTable, setShowTable] = useState(false);

  // Chart granularity controls only the trend chart (not the cards). The
  // chart's date window is auto-sized server-side based on this value:
  //   month -> last 6 months    week -> last 12 weeks    day -> last 30 days
  const [granularity, setGranularity] = useState('month');

  // Employee list for the User dropdown
  const [employees, setEmployees] = useState([]);

  // Table pagination
  const [tableOffset, setTableOffset] = useState(0);
  const [tableTotal, setTableTotal] = useState(0);
  const TABLE_LIMIT = 50;

  async function loadSummary() {
    const params = new URLSearchParams();
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    if (typeFilter) params.set('type', typeFilter);
    if (userFilter) params.set('user_name', userFilter);
    params.set('granularity', granularity);
    // Cache-only read. The dashboard never triggers a Clio sync — that's the
    // "Refresh from Clio" button's job (POST /billing/refresh). Auto-refresh
    // on load caused 502s at production data volume.
    params.set('auto_refresh', 'false');

    const data = await get(`/billing/summary?${params.toString()}`);
    setSummary(data);
  }

  async function loadActivities(offset = 0) {
    const params = new URLSearchParams();
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    if (typeFilter) params.set('type', typeFilter);
    if (userFilter) params.set('user_name', userFilter);
    params.set('limit', TABLE_LIMIT.toString());
    params.set('offset', offset.toString());
    params.set('auto_refresh', 'false');

    const data = await get(`/billing/activities?${params.toString()}`);
    setActivities(data.data || []);
    setTableTotal(data.meta?.total || 0);
    setTableOffset(offset);
  }

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      await loadSummary();
      if (showTable) await loadActivities(0);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
    get('/billing/employees').then(r => setEmployees(r.data || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reload the summary when granularity changes — the chart needs a fresh
  // server-side aggregation (different GROUP BY + different date window).
  // We skip this on the very first render because loadAll() above already runs.
  const firstGranularityRender = useRef(true);
  useEffect(() => {
    if (firstGranularityRender.current) {
      firstGranularityRender.current = false;
      return;
    }
    loadSummary().catch(err => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [granularity]);

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    setRefreshNote('Starting sync…');
    try {
      // The refresh runs in the background on the server (a full seed takes
      // minutes — longer than Azure's gateway timeout). We get back an
      // immediate "started", then poll for completion.
      // days_back applies only to the first full-window seed; subsequent
      // clicks use incremental sync (updated_since) on the server.
      await post('/billing/refresh?days_back=7', {});
      setRefreshNote('Syncing from Clio… this can take a few minutes.');

      const startedAt = Date.now();
      const MAX_MS = 15 * 60 * 1000; // give up polling after 15 min
      // Poll the status endpoint until the sync leaves the "running" state.
      // eslint-disable-next-line no-constant-condition
      while (true) {
        await new Promise((r) => setTimeout(r, 8000));
        let status;
        try {
          status = await get('/billing/refresh/status');
        } catch {
          // Transient error while the DB wakes up — keep polling.
          continue;
        }
        if (status.state !== 'running') {
          if (status.state === 'error') {
            setError(`Clio sync failed: ${status.message || 'unknown error'}`);
          }
          break;
        }
        const mins = Math.floor((Date.now() - startedAt) / 60000);
        setRefreshNote(
          `Syncing from Clio… (${mins > 0 ? `${mins} min ` : ''}elapsed). You can keep working.`,
        );
        if (Date.now() - startedAt > MAX_MS) {
          setRefreshNote('Sync is taking longer than expected — it will keep running in the background.');
          break;
        }
      }

      await loadAll();
    } catch (err) {
      // 409 = a refresh is already running (started by another tab/worker).
      setError(err.message);
    } finally {
      setRefreshing(false);
      setRefreshNote('');
    }
  }

  async function handleApplyFilters(e) {
    if (e) e.preventDefault();
    await loadAll();
    if (showTable) await loadActivities(0);
  }

  async function toggleTable() {
    const next = !showTable;
    setShowTable(next);
    if (next && activities.length === 0) {
      await loadActivities(0);
    }
  }

  const totals = summary?.totals || {};
  // by_period replaces by_month; backend still echoes by_month for compat.
  const byPeriod = summary?.by_period || summary?.by_month || [];
  const byUser = summary?.by_user || [];
  // Categories are split by type. Time entries use `activity_category`,
  // Expense entries use `expense_category` — they're separate picklists in Clio.
  const byCategoryTime = summary?.by_category_time || [];
  const byCategoryExpense = summary?.by_category_expense || [];
  const serverGranularity = summary?.granularity || granularity;

  const cacheMinutes = summary?.cache_age_seconds != null
    ? Math.round(summary.cache_age_seconds / 60)
    : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Billing & Activities</h1>
          <p className="text-sm text-slate-500 mt-1">
            Quill & Arrow Activity Data from Clio (Time & Expense Entries)
            {cacheMinutes != null && (
              <span className="ml-2 text-xs bg-slate-100 px-2 py-0.5 rounded-full">
                Last Refreshed: {cacheMinutes < 1 ? '<1' : cacheMinutes} min ago
              </span>
            )}
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition"
        >
          {refreshing ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          {refreshing ? 'Refreshing...' : 'Refresh from Clio'}
        </button>
      </div>

      {refreshNote && (
        <div className="flex items-center gap-2 text-sm text-blue-700 bg-blue-50 border border-blue-200 rounded-lg px-4 py-2">
          <Loader2 size={16} className="animate-spin" />
          {refreshNote}
        </div>
      )}

      {/* Filters */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <button
          onClick={() => setShowFilters(!showFilters)}
          className="w-full flex items-center justify-between px-5 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 transition"
        >
          <span className="flex items-center gap-2"><Filter size={16} /> Filters</span>
          {showFilters ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {showFilters && (
          <form onSubmit={handleApplyFilters} className="px-5 pb-4 grid grid-cols-1 md:grid-cols-4 gap-4 border-t border-slate-100 pt-4">
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Date From</label>
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Date To</label>
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Type</label>
              <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">All</option>
                <option value="TimeEntry">Time</option>
                <option value="ExpenseEntry">Expense</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">User</label>
              <select value={userFilter} onChange={e => setUserFilter(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">All Users</option>
                {employees.map(name => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </div>
            <div className="md:col-span-4 flex justify-end">
              <button type="submit"
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition">
                Apply Filters
              </button>
            </div>
          </form>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">{error}</div>
      )}

      {summary?.refresh_error && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-800">
          Showing cached data — the latest refresh from Clio failed: {summary.refresh_error}
        </div>
      )}

      {/* KPI Cards — labelled with the active date window so executives
          always know what period the numbers cover. */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Totals</h2>
          {(summary?.card_date_from || dateFrom) && (
            <span className="text-xs text-slate-500">
              {summary?.card_date_from || dateFrom} → {summary?.card_date_to || dateTo}
            </span>
          )}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard icon={DollarSign} label="Total Billed" value={formatCurrency(totals.total_billed)} color="bg-blue-500" loading={loading} />
          <KpiCard icon={Clock} label="Total Hours" value={formatHours(totals.total_hours)} color="bg-green-500" loading={loading} />
          <KpiCard icon={TrendingUp} label="Time Entries" value={totals.time_entries ?? '...'} subtitle={formatCurrency(totals.time_total)} color="bg-purple-500" loading={loading} />
          <KpiCard icon={FileText} label="Expense Entries" value={totals.expense_entries ?? '...'} subtitle={formatCurrency(totals.expense_total)} color="bg-amber-500" loading={loading} />
        </div>
      </div>

      {/* Charts Row */}
      {!loading && (
        <div className="grid grid-cols-1 gap-6">
          {/* Trend Bar Chart — full width while By Attorney is disabled */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <div className="flex items-start justify-between mb-4 gap-4">
              <div>
                <h3 className="text-sm font-semibold text-slate-700">
                  {GRANULARITY_LABELS[serverGranularity]?.title || 'Activity Totals'}
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  {GRANULARITY_LABELS[serverGranularity]?.subtitle}
                </p>
              </div>
              <div className="flex items-center gap-3 flex-wrap justify-end">
                <select
                  value={granularity}
                  onChange={e => setGranularity(e.target.value)}
                  className="text-xs px-2.5 py-1.5 border border-slate-300 rounded-lg bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  aria-label="Chart granularity"
                >
                  <option value="month">By Month</option>
                  <option value="week">By Week</option>
                  <option value="day">By Day</option>
                </select>
                <div className="flex items-center gap-3 text-xs text-slate-500">
                  <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: BAR_COLORS[0] }} /> Time</span>
                  <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: BAR_COLORS[1] }} /> Expenses</span>
                </div>
              </div>
            </div>
            <MonthlyBarChart data={byPeriod} granularity={serverGranularity} />
          </div>

          {/* By User/Attorney Breakdown — temporarily disabled for Prod
              until Manufacturing Pod Groups are built. Re-enable by removing
              the false && condition below. The backend still returns by_user
              data so when pods are ready, just flip this back on. */}
          {false && (
            <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-4">By Attorney</h3>
              <AttorneyBreakdown data={byUser} />
            </div>
          )}
        </div>
      )}

      {/* Activity Category Breakdown — split by type because Time entries
          and Expense entries use different category pickers in Clio. */}
      {!loading && (byCategoryTime.length > 0 || byCategoryExpense.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Time categories */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-slate-700">Top Time Categories</h3>
              <span className="text-xs text-slate-400">Activity Description</span>
            </div>
            <CategoryList
              data={byCategoryTime}
              emptyMessage="No time entries in this period"
            />
          </div>

          {/* Expense categories */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-slate-700">Top Expense Categories</h3>
              <span className="text-xs text-slate-400">Expense Category</span>
            </div>
            <CategoryList
              data={byCategoryExpense}
              emptyMessage="No expense entries in this period"
            />
          </div>
        </div>
      )}

      {/* ──────────────────────────────────────────────────────────────────
          Activity Detail Table — COMMENTED OUT for Prod launch.
          With 2,000-3,000 daily entries in Prod this table would be
          overwhelming and users can view detail in Clio directly.
          Re-enable later if users request it.
          ──────────────────────────────────────────────────────────────────
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <button
          onClick={toggleTable}
          className="w-full flex items-center justify-between px-5 py-4 text-sm font-medium text-slate-700 hover:bg-slate-50 transition"
        >
          <span className="flex items-center gap-2"><Users size={16} /> Activity Detail Table ({tableTotal} records)</span>
          {showTable ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>

        {showTable && (
          <div className="border-t border-slate-100">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 border-b border-slate-200">
                  <tr>
                    <th className="px-4 py-2.5 text-left font-medium text-slate-600">Date</th>
                    <th className="px-4 py-2.5 text-left font-medium text-slate-600">Type</th>
                    <th className="px-4 py-2.5 text-left font-medium text-slate-600">User</th>
                    <th className="px-4 py-2.5 text-left font-medium text-slate-600">Matter</th>
                    <th className="px-4 py-2.5 text-left font-medium text-slate-600">Category</th>
                    <th className="px-4 py-2.5 text-right font-medium text-slate-600">Hours</th>
                    <th className="px-4 py-2.5 text-right font-medium text-slate-600">Rate</th>
                    <th className="px-4 py-2.5 text-right font-medium text-slate-600">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {activities.map(a => (
                    <tr key={a.id} className="hover:bg-slate-50">
                      <td className="px-4 py-2 text-slate-700">{a.date}</td>
                      <td className="px-4 py-2">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${
                          a.type === 'TimeEntry' ? 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-700'
                        }`}>
                          {a.type === 'TimeEntry' ? 'Time' : 'Expense'}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-slate-700">{a.user_name || '—'}</td>
                      <td className="px-4 py-2 text-slate-600 max-w-48 truncate" title={a.matter_description}>
                        {a.matter_display_number || '—'}
                      </td>
                      <td className="px-4 py-2 text-slate-600">{a.activity_category || a.expense_category || '—'}</td>
                      <td className="px-4 py-2 text-right text-slate-700">{a.quantity ? Number(a.quantity).toFixed(1) : '—'}</td>
                      <td className="px-4 py-2 text-right text-slate-700">{a.price != null ? `$${Number(a.price).toFixed(0)}` : '—'}</td>
                      <td className="px-4 py-2 text-right font-medium text-slate-800">{a.total != null ? formatCurrency(a.total) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {tableTotal > TABLE_LIMIT && (
              <div className="flex items-center justify-between px-5 py-3 border-t border-slate-100">
                <span className="text-xs text-slate-500">
                  Showing {tableOffset + 1}–{Math.min(tableOffset + TABLE_LIMIT, tableTotal)} of {tableTotal}
                </span>
                <div className="flex gap-2">
                  <button
                    onClick={() => loadActivities(Math.max(0, tableOffset - TABLE_LIMIT))}
                    disabled={tableOffset === 0}
                    className="px-3 py-1.5 text-xs border border-slate-300 rounded-lg disabled:opacity-40 hover:bg-slate-50"
                  >Previous</button>
                  <button
                    onClick={() => loadActivities(tableOffset + TABLE_LIMIT)}
                    disabled={tableOffset + TABLE_LIMIT >= tableTotal}
                    className="px-3 py-1.5 text-xs border border-slate-300 rounded-lg disabled:opacity-40 hover:bg-slate-50"
                  >Next</button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
      ────────────────────────────────────────────────────────────────── */}
    </div>
  );
}
