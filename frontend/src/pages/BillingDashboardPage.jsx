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

// Chart.js stacked bar chart with tooltips and axis labels.
// Uses Chart.js directly via useRef/useEffect to avoid React 19 incompatibilities
// in third-party wrappers (we hit similar issues with recharts and react-chartjs-2).
function MonthlyBarChart({ data }) {
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

    chartRef.current = new Chart(canvasRef.current, {
      type: 'bar',
      data: {
        labels: data.map(d => d.month),
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
  }, [data]);

  if (!data || data.length === 0) {
    return <p className="text-sm text-slate-400 text-center py-12">No Data Found for Selected Period</p>;
  }

  return (
    <div className="h-56">
      <canvas ref={canvasRef} />
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
  const [error, setError] = useState(null);

  // Filters
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [userFilter, setUserFilter] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [showTable, setShowTable] = useState(false);

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
    params.set('auto_refresh', 'true');

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
  }, []);

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      await post('/billing/refresh', { days_back: 90 });
      await loadAll();
    } catch (err) {
      setError(err.message);
    } finally {
      setRefreshing(false);
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
  const byMonth = summary?.by_month || [];
  const byUser = summary?.by_user || [];
  const byCategory = summary?.by_category || [];

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

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard icon={DollarSign} label="Total Billed" value={formatCurrency(totals.total_billed)} color="bg-blue-500" loading={loading} />
        <KpiCard icon={Clock} label="Total Hours" value={formatHours(totals.total_hours)} color="bg-green-500" loading={loading} />
        <KpiCard icon={TrendingUp} label="Time Entries" value={totals.time_entries ?? '...'} subtitle={formatCurrency(totals.time_total)} color="bg-purple-500" loading={loading} />
        <KpiCard icon={FileText} label="Expense Entries" value={totals.expense_entries ?? '...'} subtitle={formatCurrency(totals.expense_total)} color="bg-amber-500" loading={loading} />
      </div>

      {/* Charts Row */}
      {!loading && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Monthly Bar Chart */}
          <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-slate-700">Monthly Activity Totals</h3>
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: BAR_COLORS[0] }} /> Time</span>
                <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: BAR_COLORS[1] }} /> Expenses</span>
              </div>
            </div>
            <MonthlyBarChart data={byMonth} />
          </div>

          {/* By User Breakdown */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-4">By Attorney</h3>
            <AttorneyBreakdown data={byUser} />
          </div>
        </div>
      )}

      {/* Activity Category Breakdown */}
      {!loading && byCategory.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-3">Top Activity Categories</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {byCategory.map((cat, i) => {
              const maxTotal = byCategory[0]?.total || 1;
              const pct = (cat.total / maxTotal) * 100;
              return (
                <div key={cat.category} className="flex items-center gap-3">
                  <span className="w-28 text-xs text-slate-600 truncate">{cat.category}</span>
                  <div className="flex-1 bg-slate-100 rounded-full h-2.5">
                    <div className="h-2.5 rounded-full" style={{ width: `${pct}%`, backgroundColor: PIE_COLORS[i % PIE_COLORS.length] }} />
                  </div>
                  <span className="text-xs text-slate-500 w-16 text-right">{formatCurrency(cat.total)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Expandable Data Table */}
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

            {/* Pagination */}
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
    </div>
  );
}
