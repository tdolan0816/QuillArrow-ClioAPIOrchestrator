/**
 * Firm Wide Dashboard — landing page after login.
 *
 * Matter KPIs for stakeholders, all bucketed by the "Matter Filed Date"
 * custom field and split by the "Jurisdiction" custom field:
 *   - Filters (Date From / Date To / Jurisdiction)
 *   - Firm Wide Matter Totals (Total / Open / Pending / Closed) + trend chart
 *   - Matter Totals by Jurisdiction (State row, Federal row) + trend chart
 *     with Time Interval / Jurisdiction / Matter Status dropdowns
 *
 * Data comes from the matters cache (backend/routes/firm_dashboard.py); the
 * "Refresh from Clio" button starts a background sync and polls, exactly like
 * the Billing & Activities dashboard.
 */

import { useState, useEffect, useRef, useMemo } from 'react';
import { get, post } from '../api/client';
import {
  Briefcase,
  FolderOpen,
  Hourglass,
  FolderCheck,
  RefreshCw,
  Loader2,
  Filter,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
// Chart.js via the canvas API directly (not react-chartjs-2) for React 19 compatibility.
import Chart from 'chart.js/auto';
import { useTheme } from '../context/ThemeContext';
import { CHART_THEME } from '../lib/chartTheme';
import KpiCard from '../components/KpiCard';
import {
  formatLongDate,
  formatPeriodLabel,
  todayISO,
  firstOfMonthMonthsAgoISO,
} from '../lib/dashboardFormat';

// ── Chart colors — EDIT HERE to re-theme the matter trend bars ──────────────
// One bar color per Matter Status selection; used for the bar fill and the
// tooltip swatch.
const STATUS_COLORS = {
  Total: '#3b82f6',   // blue
  Open: '#10b981',    // green
  Pending: '#f59e0b', // amber
  Closed: '#64748b',  // slate
};

const STATUS_OPTIONS = ['Total', 'Open', 'Pending', 'Closed'];
const JURISDICTION_OPTIONS = ['State', 'Federal', 'Arbitration'];

const GRANULARITY_TITLES = {
  day: 'Daily Matters Filed',
  week: 'Weekly Matters Filed',
  month: 'Monthly Matters Filed',
};

// Build the complete list of period keys between two dates so periods with
// zero matters still appear as empty bars (for month + day; week numbering
// differs by SQL dialect so weeks just use whatever the server returned).
function fillPeriods(rows, granularity, dateFrom, dateTo) {
  const present = new Set(rows.map(r => r.period));
  if (granularity === 'week' || !dateFrom || !dateTo) {
    return [...present].sort();
  }
  const keys = new Set(present);
  const [fy, fm, fd] = dateFrom.split('-').map(Number);
  const [ty, tm, td] = dateTo.split('-').map(Number);
  if (granularity === 'month') {
    const cur = new Date(fy, fm - 1, 1);
    const end = new Date(ty, tm - 1, 1);
    let guard = 0;
    while (cur <= end && guard++ < 600) {
      keys.add(`${cur.getFullYear()}-${String(cur.getMonth() + 1).padStart(2, '0')}`);
      cur.setMonth(cur.getMonth() + 1);
    }
  } else {
    const cur = new Date(fy, fm - 1, fd);
    const end = new Date(ty, tm - 1, td);
    let guard = 0;
    while (cur <= end && guard++ < 1000) {
      keys.add(`${cur.getFullYear()}-${String(cur.getMonth() + 1).padStart(2, '0')}-${String(cur.getDate()).padStart(2, '0')}`);
      cur.setDate(cur.getDate() + 1);
    }
  }
  return [...keys].sort();
}

// Collapse the flat (period × jurisdiction × status) rows into one series
// for the chart's current dropdown selection.
function seriesFor(rows, { status, jurisdiction, granularity, dateFrom, dateTo }) {
  const filtered = rows.filter(r =>
    (!jurisdiction || r.jurisdiction === jurisdiction)
    && (status === 'Total' || r.status === status)
  );
  const periods = fillPeriods(filtered.length ? filtered : rows, granularity, dateFrom, dateTo);
  const counts = new Map(periods.map(p => [p, 0]));
  filtered.forEach(r => counts.set(r.period, (counts.get(r.period) || 0) + r.count));
  return { labels: periods.map(p => formatPeriodLabel(p, granularity)), data: periods.map(p => counts.get(p) || 0) };
}

// Chart.js bar chart: Time on X, Matter Quantity on Y. Mirrors MonthlyBarChart
// on the Billing dashboard (same tooltip/axis theming via CHART_THEME).
function MattersTrendChart({ series, color }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);
  const { theme } = useTheme();
  const t = CHART_THEME[theme];
  const hasData = series.data.some(v => v > 0);

  useEffect(() => {
    if (!canvasRef.current || !hasData) return;
    if (chartRef.current) {
      chartRef.current.destroy();
      chartRef.current = null;
    }
    chartRef.current = new Chart(canvasRef.current, {
      type: 'bar',
      data: {
        labels: series.labels,
        datasets: [{
          label: 'Matters',
          data: series.data,
          backgroundColor: color,
          borderRadius: 0,
          borderSkipped: false,
          maxBarThickness: 48,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            grid: { display: false },
            ticks: { font: { size: 11 }, color: t.tick, autoSkip: true, maxRotation: 0 },
            title: { display: true, text: 'Matter Filed Date', color: t.tick, font: { size: 11 } },
          },
          y: {
            beginAtZero: true,
            grid: { color: t.grid },
            ticks: { font: { size: 11 }, color: t.tick, precision: 0 },
            title: { display: true, text: 'Matter Quantity', color: t.tick, font: { size: 11 } },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: t.tooltipBg,
            titleColor: t.tooltipTitle,
            bodyColor: t.tooltipBody,
            padding: 12,
            cornerRadius: 8,
            displayColors: true,
            callbacks: {
              label: ctx => `Matters: ${Number(ctx.parsed.y).toLocaleString('en-US')}`,
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
  }, [series, color, theme, hasData, t]); // theme: re-create with the new palette on toggle

  if (!hasData) {
    return <p className="text-sm text-slate-400 text-center py-12">No Matters Found for Selected Period</p>;
  }
  return (
    <div className="h-64">
      <canvas ref={canvasRef} />
    </div>
  );
}

const selectClass = 'px-3 py-1.5 border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-700 dark:text-slate-100 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500';
const inputClass = 'w-full px-3 py-2 border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500';
const labelClass = 'block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1';

function fmtCount(n) {
  return n == null ? '...' : Number(n).toLocaleString('en-US');
}

// Four status cards for one bucket (firm-wide, State, or Federal).
function StatusCards({ bucket, suffix = '', loading }) {
  const b = bucket || {};
  const label = s => (suffix ? `${s} - ${suffix}` : s);
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <KpiCard icon={Briefcase} label={label('Total Matters')} value={fmtCount(b.total)} color="bg-blue-500" loading={loading} />
      <KpiCard icon={FolderOpen} label={label('Total Open')} value={fmtCount(b.open)} color="bg-green-500" loading={loading} />
      <KpiCard icon={Hourglass} label={label('Total Pending')} value={fmtCount(b.pending)} color="bg-amber-500" loading={loading} />
      <KpiCard icon={FolderCheck} label={label('Total Closed')} value={fmtCount(b.closed)} color="bg-slate-500" loading={loading} />
    </div>
  );
}

function ChartCard({ title, subtitle, controls, children }) {
  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm p-5">
      <div className="flex items-start justify-between mb-4 gap-4 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</h3>
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">{subtitle}</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap justify-end">{controls}</div>
      </div>
      {children}
    </div>
  );
}

export default function DashboardPage() {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNote, setRefreshNote] = useState('');
  const [error, setError] = useState(null);

  // Filters — default to the trailing 12 months of filed matters.
  const [dateFrom, setDateFrom] = useState(() => firstOfMonthMonthsAgoISO(11));
  const [dateTo, setDateTo] = useState(todayISO);
  const [jurisdiction, setJurisdiction] = useState('');
  const [showFilters, setShowFilters] = useState(false);

  // Chart 1 (firm-wide): interval + status. Follows the filter card's jurisdiction.
  const [granA, setGranA] = useState('month');
  const [statusA, setStatusA] = useState('Total');
  const [trendA, setTrendA] = useState({ rows: [], granularity: 'month' });
  // Chart 2 (by jurisdiction): interval + jurisdiction + status.
  const [granB, setGranB] = useState('month');
  const [jurB, setJurB] = useState('');
  const [statusB, setStatusB] = useState('Total');
  const [trendB, setTrendB] = useState({ rows: [], granularity: 'month' });

  function rangeParams() {
    const params = new URLSearchParams();
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    return params;
  }

  async function loadSummary() {
    const params = rangeParams();
    if (jurisdiction) params.set('jurisdiction', jurisdiction);
    setSummary(await get(`/firm/summary?${params.toString()}`));
  }

  async function loadTrend(granularity) {
    const params = rangeParams();
    params.set('granularity', granularity);
    const data = await get(`/firm/trend?${params.toString()}`);
    return { rows: data.rows || [], granularity: data.granularity || granularity, dateFrom: data.date_from, dateTo: data.date_to };
  }

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const [, a, b] = await Promise.all([loadSummary(), loadTrend(granA), granB === granA ? null : loadTrend(granB)]);
      setTrendA(a);
      setTrendB(b || a);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Interval dropdowns need a server re-aggregation (different GROUP BY).
  const firstA = useRef(true);
  useEffect(() => {
    if (firstA.current) { firstA.current = false; return; }
    loadTrend(granA).then(setTrendA).catch(err => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [granA]);
  const firstB = useRef(true);
  useEffect(() => {
    if (firstB.current) { firstB.current = false; return; }
    loadTrend(granB).then(setTrendB).catch(err => setError(err.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [granB]);

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    setRefreshNote('Starting sync…');
    try {
      await post('/firm/refresh', {});
      setRefreshNote('Syncing matters from Clio… this can take a few minutes. You can keep working.');
      const startedAt = Date.now();
      const MAX_MS = 20 * 60 * 1000;
      // eslint-disable-next-line no-constant-condition
      while (true) {
        await new Promise(r => setTimeout(r, 8000));
        let status;
        try {
          status = await get('/firm/refresh/status');
        } catch {
          continue;
        }
        if (status.state !== 'running') {
          if (status.state === 'error') setError(`Clio sync failed: ${status.message || 'unknown error'}`);
          break;
        }
        const mins = Math.floor((Date.now() - startedAt) / 60000);
        setRefreshNote(`${status.message || 'Syncing from Clio…'} (${mins > 0 ? `${mins} min ` : ''}elapsed). You can keep working.`);
        if (Date.now() - startedAt > MAX_MS) {
          setRefreshNote('Sync is taking longer than expected — it will keep running in the background.');
          break;
        }
      }
      await loadAll();
    } catch (err) {
      setError(err.message); // 409 = a refresh is already running
    } finally {
      setRefreshing(false);
      setRefreshNote('');
    }
  }

  async function handleApplyFilters(e) {
    if (e) e.preventDefault();
    await loadAll();
  }

  const appliedFrom = summary?.date_from || dateFrom;
  const appliedTo = summary?.date_to || dateTo;
  const totals = summary?.totals;
  const byJur = summary?.by_jurisdiction || {};
  const cacheEmpty = summary && summary.cached_matters === 0;
  const cacheMinutes = summary?.cache_age_seconds != null ? Math.round(summary.cache_age_seconds / 60) : null;

  const seriesA = useMemo(() => seriesFor(trendA.rows, {
    status: statusA, jurisdiction, granularity: trendA.granularity, dateFrom: trendA.dateFrom || appliedFrom, dateTo: trendA.dateTo || appliedTo,
  }), [trendA, statusA, jurisdiction, appliedFrom, appliedTo]);
  const seriesB = useMemo(() => seriesFor(trendB.rows, {
    status: statusB, jurisdiction: jurB, granularity: trendB.granularity, dateFrom: trendB.dateFrom || appliedFrom, dateTo: trendB.dateTo || appliedTo,
  }), [trendB, statusB, jurB, appliedFrom, appliedTo]);

  const timeframeLabel = `${formatLongDate(appliedFrom)} through ${formatLongDate(appliedTo)}`;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Firm Wide Dashboard</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Quill & Arrow Matter Data for State, Federal, and Firm Totals (by Matter Filed Date)
            {cacheMinutes != null && (
              <span className="ml-2 text-xs bg-slate-100 dark:bg-slate-700 dark:text-slate-300 px-2 py-0.5 rounded-full">
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
        <div className="flex items-center gap-2 text-sm text-blue-700 dark:text-blue-200 bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-lg px-4 py-2">
          <Loader2 size={16} className="animate-spin" />
          {refreshNote}
        </div>
      )}

      {/* Filters */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 shadow-sm">
        <button
          onClick={() => setShowFilters(!showFilters)}
          className="w-full flex items-center justify-between px-5 py-3 text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 transition"
        >
          <span className="flex items-center gap-2"><Filter size={16} /> Filters</span>
          {showFilters ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {showFilters && (
          <form onSubmit={handleApplyFilters} className="px-5 pb-4 grid grid-cols-1 md:grid-cols-3 gap-4 border-t border-slate-100 dark:border-slate-700 pt-4">
            <div>
              <label className={labelClass}>Date From</label>
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Date To</label>
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className={inputClass} />
            </div>
            <div>
              <label className={labelClass}>Jurisdiction</label>
              <select value={jurisdiction} onChange={e => setJurisdiction(e.target.value)} className={inputClass}>
                <option value="">All Jurisdictions</option>
                {JURISDICTION_OPTIONS.map(j => <option key={j} value={j}>{j}</option>)}
              </select>
            </div>
            <div className="md:col-span-3 flex justify-end">
              <button type="submit" className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition">
                Apply Filters
              </button>
            </div>
          </form>
        )}
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg p-4 text-sm text-red-700 dark:text-red-200">{error}</div>
      )}

      {cacheEmpty && !refreshing && (
        <div className="bg-yellow-50 dark:bg-yellow-950 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 text-sm text-yellow-800 dark:text-yellow-200">
          No matter data has been loaded yet. Click <span className="font-semibold">Refresh from Clio</span> to pull the firm's matters (first load can take several minutes).
        </div>
      )}

      {/* Firm Wide Matter Totals */}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <h2 className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">Firm Wide Matter Totals</h2>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
            <span className="text-slate-600 dark:text-slate-300">
              <span className="font-semibold text-slate-800 dark:text-slate-100">Viewing:</span>{' '}
              {jurisdiction ? `${jurisdiction} Matters` : 'All Jurisdictions'}
            </span>
            <span className="text-slate-600 dark:text-slate-300">
              <span className="font-semibold text-slate-800 dark:text-slate-100">Timeframe:</span>{' '}
              {timeframeLabel}
            </span>
          </div>
        </div>
        <StatusCards bucket={totals} loading={loading} />
        {summary?.unfiled_matters > 0 && (
          <p className="text-xs text-slate-400 dark:text-slate-500 mt-2">
            {summary.unfiled_matters.toLocaleString('en-US')} matters have no Matter Filed Date in Clio and are not included in date-based totals.
          </p>
        )}
      </div>

      {!loading && (
        <ChartCard
          title={GRANULARITY_TITLES[trendA.granularity] || 'Matters Filed'}
          subtitle={`${statusA === 'Total' ? 'All' : statusA} matters · ${jurisdiction || 'All Jurisdictions'} · ${timeframeLabel}`}
          controls={(
            <>
              <select value={granA} onChange={e => setGranA(e.target.value)} className={selectClass} aria-label="Time interval">
                <option value="month">Month</option>
                <option value="week">Week</option>
                <option value="day">Day</option>
              </select>
              <select value={statusA} onChange={e => setStatusA(e.target.value)} className={selectClass} aria-label="Matter status">
                {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </>
          )}
        >
          <MattersTrendChart series={seriesA} color={STATUS_COLORS[statusA]} />
        </ChartCard>
      )}

      {/* Matter Totals by Jurisdiction */}
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">Matter Totals by State and Federal</h2>
          <span className="text-xs text-slate-400 dark:text-slate-500">
            Blank Jurisdiction counted as State · Arbitration: {fmtCount(byJur.Arbitration?.total ?? (loading ? null : 0))} matters
          </span>
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-2">State</div>
          <StatusCards bucket={byJur.State} suffix="State" loading={loading} />
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-2">Federal</div>
          <StatusCards bucket={byJur.Federal} suffix="Federal" loading={loading} />
        </div>
      </div>

      {!loading && (
        <ChartCard
          title={`${GRANULARITY_TITLES[trendB.granularity] || 'Matters Filed'} by Jurisdiction`}
          subtitle={`${statusB === 'Total' ? 'All' : statusB} matters · ${jurB || 'All Jurisdictions'} · ${timeframeLabel}`}
          controls={(
            <>
              <select value={granB} onChange={e => setGranB(e.target.value)} className={selectClass} aria-label="Time interval">
                <option value="month">Month</option>
                <option value="week">Week</option>
                <option value="day">Day</option>
              </select>
              <select value={jurB} onChange={e => setJurB(e.target.value)} className={selectClass} aria-label="Jurisdiction">
                <option value="">All Jurisdictions</option>
                {JURISDICTION_OPTIONS.map(j => <option key={j} value={j}>{j}</option>)}
              </select>
              <select value={statusB} onChange={e => setStatusB(e.target.value)} className={selectClass} aria-label="Matter status">
                {STATUS_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </>
          )}
        >
          <MattersTrendChart series={seriesB} color={STATUS_COLORS[statusB]} />
        </ChartCard>
      )}
    </div>
  );
}
