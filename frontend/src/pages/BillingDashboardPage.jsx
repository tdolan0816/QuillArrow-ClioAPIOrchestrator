/**
 * Billing & Activities Dashboard
 *
 * Shows firm activity data from Clio (Time + Expense entries) with:
 *   - KPI cards (total billed, hours, entries)
 *   - Bar chart: monthly totals (time vs expense)
 *   - Pie chart: breakdown by attorney
 *   - Data table with filters
 */

import { useState, useEffect } from 'react';
import { get, post } from '../api/client';
import {
  DollarSign,
  Clock,
  FileText,
  RefreshCw,
  Loader2,
  TrendingUp,
  Users,
  Filter,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';

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

  // Table pagination
  const [tableOffset, setTableOffset] = useState(0);
  const [tableTotal, setTableTotal] = useState(0);
  const TABLE_LIMIT = 50;

  async function loadSummary() {
    const params = new URLSearchParams();
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
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

  useEffect(() => { loadAll(); }, []);

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
            Firm activity data from Clio (Time & Expense entries)
            {cacheMinutes != null && (
              <span className="ml-2 text-xs bg-slate-100 px-2 py-0.5 rounded-full">
                Cache: {cacheMinutes < 1 ? '<1' : cacheMinutes} min ago
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
              <input type="text" value={userFilter} onChange={e => setUserFilter(e.target.value)}
                placeholder="Filter by name..."
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
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

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard icon={DollarSign} label="Total Billed" value={formatCurrency(totals.total_billed)} color="bg-blue-500" loading={loading} />
        <KpiCard icon={Clock} label="Total Hours" value={formatHours(totals.total_hours)} color="bg-green-500" loading={loading} />
        <KpiCard icon={TrendingUp} label="Time Entries" value={totals.time_entries ?? '...'} subtitle={`${formatCurrency(totals.time_total)}`} color="bg-purple-500" loading={loading} />
        <KpiCard icon={FileText} label="Expense Entries" value={totals.expense_entries ?? '...'} subtitle={`${formatCurrency(totals.expense_total)}`} color="bg-amber-500" loading={loading} />
      </div>

      {/* Charts Row */}
      {!loading && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Monthly Bar Chart */}
          <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-4">Monthly Activity Totals</h3>
            {byMonth.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={byMonth} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
                  <Tooltip formatter={(v) => formatCurrency(v)} />
                  <Legend />
                  <Bar dataKey="time_total" name="Time" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="expense_total" name="Expenses" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-sm text-slate-400 text-center py-12">No data for selected period</p>
            )}
          </div>

          {/* By User Pie Chart */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-4">By Attorney</h3>
            {byUser.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie
                      data={byUser}
                      dataKey="total"
                      nameKey="user_name"
                      cx="50%"
                      cy="50%"
                      outerRadius={75}
                      label={({ user_name, percent }) => `${(user_name || '').split(' ')[0]} ${(percent * 100).toFixed(0)}%`}
                      labelLine={false}
                    >
                      {byUser.map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v) => formatCurrency(v)} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="mt-3 space-y-1.5">
                  {byUser.slice(0, 6).map((u, i) => (
                    <div key={u.user_name} className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: PIE_COLORS[i % PIE_COLORS.length] }} />
                        {u.user_name || 'Unknown'}
                      </span>
                      <span className="text-slate-500">{formatCurrency(u.total)} · {formatHours(u.hours)}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-sm text-slate-400 text-center py-12">No data</p>
            )}
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
