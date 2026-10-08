/**
 * Billing & Activities Dashboard
 *
 * Shows firm activity data from Clio (Time + Expense entries) with:
 *   - KPI cards (total billed, hours, entries)
 *   - Monthly bar chart (Chart.js stacked bar with tooltips)
 *   - Breakdown by attorney
 *   - Data table with filters
 */

import { useState, useEffect, useRef, useMemo } from 'react';
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
  Award,
  CalendarDays,
  Timer,
  Info,
} from 'lucide-react';
// Chart.js with auto-registration of all components.
// We use the canvas API directly (not react-chartjs-2) for React 19 compatibility.
import Chart from 'chart.js/auto';

const BAR_COLORS = ['#3b82f6', '#10b981'];
const PIE_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#f97316', '#84cc16', '#ec4899', '#6366f1',
];

// ── Donut color palettes — EDIT HERE to re-theme the Top Category donuts ────
// Slice order follows category rank (1st → 10th). The same color is used for
// the donut slice and its tooltip swatch, so changing a hex here re-themes
// both. Time = blues, Expenses = greens/teals to match the current mockup;
// swap any values to suit stakeholder preference.
const TIME_DONUT_COLORS = [
  '#1d4ed8', '#3b82f6', '#60a5fa', '#93c5fd', '#2563eb',
  '#38bdf8', '#0ea5e9', '#1e40af', '#bfdbfe', '#7dd3fc',
];
const EXPENSE_DONUT_COLORS = [
  '#047857', '#10b981', '#34d399', '#6ee7b7', '#059669',
  '#2dd4bf', '#14b8a6', '#065f46', '#a7f3d0', '#5eead4',
];

// ── Pod Member scorecard settings — EDIT HERE to re-theme the KPI gauges ────
// Speedometer gauges on each Individual Pod Member scorecard.
const GAUGE_COLORS = {
  zones: ['#ef4444', '#facc15', '#4ade80', '#15803d'], // Q1, Q2, Q3, Q4 bands
  zoneLabel: '#1e293b',      // "Q1".."Q4" text on the bands
  needle: '#0f172a',         // needle + hub
  meanLine: '#dc2626',       // red pod-average marker
  tick: '#475569',           // range labels at the gauge ends
  figure: '#2563eb',         // main metric figure (normal)
  figureAlert: '#dc2626',    // main metric figure when below the pod median
};
// Gauge range ceilings are the pod max rounded UP to these multiples, so every
// member in a pod shares identical ranges and quartile zones.
const GAUGE_RANGE_STEPS = {
  billed: 1000,       // $11,351 → $12,000
  hours: 100,         // 243.5h → 300h
  pctVsMedian: 100,   // 226.5% → 300%
};
// Six-Month Trend column chart.
const TREND_COLORS = {
  bar: '#4a90c2',        // column fill
  barBorder: '#2b5f85',  // column outline
  line: '#dc2626',       // red trend line
  point: '#dc2626',      // trend points
};

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

// Pod KPI card — shows the winning pod member + their metric figure, with a
// hover "info box" (styled like the bar chart tooltip) explaining the metric
// and the calculation behind it.
function PodKpiCard({ icon: Icon, label, name, figure, subtitle, color, info, loading }) {
  return (
    <div className="relative group bg-white rounded-xl p-5 shadow-sm border border-slate-200 cursor-default">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium text-slate-500">{label}</span>
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${color}`}>
          <Icon size={18} className="text-white" />
        </div>
      </div>
      {loading ? (
        <div className="text-2xl font-bold text-slate-800">...</div>
      ) : name ? (
        <>
          <div className="text-lg font-bold text-slate-800 truncate" title={name}>{name}</div>
          <div className="text-xl font-bold text-blue-600 mt-0.5">{figure}</div>
          {subtitle && <p className="text-xs text-slate-400 mt-1">{subtitle}</p>}
        </>
      ) : (
        <div className="text-sm text-slate-400 py-2">No data for this selection</div>
      )}

      {/* Hover info box — mirrors the Monthly Activity chart tooltip styling */}
      <div className="pointer-events-none absolute left-1/2 -translate-x-1/2 top-full mt-2 w-80 z-20 opacity-0 group-hover:opacity-100 transition-opacity duration-150 bg-slate-800 text-slate-50 text-xs rounded-lg p-3.5 shadow-xl">
        <p className="font-semibold text-center mb-1.5">{info.title}</p>
        <p className="text-slate-200 text-center leading-relaxed mb-1.5">{info.description}</p>
        <p className="text-slate-300 text-center leading-relaxed">
          <span className="font-semibold text-slate-100">Calculation:</span> {info.calculation}
        </p>
      </div>
    </div>
  );
}

function formatCurrency(val) {
  if (val == null) return '$0.00';
  // Show exact cents — the stored values are penny-accurate, so don't round.
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(val);
}

function formatHours(val) {
  if (val == null) return '0h';
  return `${Number(val).toFixed(1)}h`;
}

// "2026-06-01" -> "June 1, 2026" for the Viewing/Timeframe context label.
function formatLongDate(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString('en-US', {
    month: 'long', day: 'numeric', year: 'numeric',
  });
}

// "2026-09-01" -> "Sept 1st '26" — the abbreviated Timeframe shown in the
// Top Category donut tooltips. Mirrors the full "Timeframe:" label above the
// Totals cards, just compacted to fit a tooltip.
const SHORT_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sept', 'Oct', 'Nov', 'Dec'];

function ordinalDay(n) {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  switch (n % 10) {
    case 1: return `${n}st`;
    case 2: return `${n}nd`;
    case 3: return `${n}rd`;
    default: return `${n}th`;
  }
}

function formatShortRangeDate(iso) {
  if (!iso) return '';
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return iso;
  return `${SHORT_MONTHS[m - 1]} ${ordinalDay(d)} '${String(y).slice(-2)}`;
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

// Donut chart used inside the split "Top Categories" cards: donut on the
// left, "Category: $amount" list on the right. Hovering a slice shows a
// tooltip with the abbreviated Timeframe span (upper-left, smaller font),
// then a color swatch matching the slice plus the same "Category: $amount"
// line. Chart.js is used directly via refs for the same React 19
// compatibility reasons as MonthlyBarChart. The `colors` prop controls the
// palette — see TIME_DONUT_COLORS / EXPENSE_DONUT_COLORS near the top of
// this file to re-theme.
function CategoryDonut({ data, colors, rangeLabel, emptyMessage = 'No data for this period' }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current) return;
    if (!data || data.length === 0) return;

    if (chartRef.current) {
      chartRef.current.destroy();
      chartRef.current = null;
    }

    chartRef.current = new Chart(canvasRef.current, {
      type: 'doughnut',
      data: {
        labels: data.map(d => d.category || 'Uncategorized'),
        datasets: [
          {
            data: data.map(d => d.total || 0),
            backgroundColor: data.map((_, i) => colors[i % colors.length]),
            borderColor: '#ffffff',
            borderWidth: 2,
            hoverOffset: 6,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '60%',
        layout: { padding: 6 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#1e293b',
            titleColor: '#cbd5e1',
            titleFont: { size: 10, weight: 'normal' },
            titleAlign: 'left',
            titleMarginBottom: 8,
            bodyColor: '#f8fafc',
            bodyFont: { size: 12, weight: 'bold' },
            padding: 12,
            cornerRadius: 8,
            displayColors: true,
            boxWidth: 12,
            boxHeight: 12,
            boxPadding: 4,
            callbacks: {
              title: () => rangeLabel || '',
              label: context => `${context.label}: ${formatCurrency(context.parsed)}`,
            },
          },
        },
      },
    });

    return () => {
      if (chartRef.current) {
        chartRef.current.destroy();
        chartRef.current = null;
      }
    };
  }, [data, colors, rangeLabel]);

  if (!data || data.length === 0) {
    return <p className="text-sm text-slate-400 text-center py-6">{emptyMessage}</p>;
  }

  return (
    <div className="flex items-center gap-6">
      <div className="relative w-44 h-44 shrink-0">
        <canvas ref={canvasRef} />
      </div>
      <div className="flex-1 min-w-0 space-y-1.5">
        {data.map((cat, i) => (
          <div key={(cat.category || '') + i} className="flex items-baseline gap-1.5 text-sm min-w-0" title={cat.category}>
            <span className="font-semibold text-slate-800 truncate">{cat.category || 'Uncategorized'}:</span>
            <span className="text-slate-600 whitespace-nowrap">{formatCurrency(cat.total)}</span>
          </div>
        ))}
      </div>
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

// "2026-06" -> "Jun '26" for sparkline tooltips.
function formatMonthShort(ym) {
  const [y, m] = (ym || '').split('-').map(Number);
  if (!y || !m) return ym;
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'short' }) + ` '${String(y).slice(-2)}`;
}

// Six-Month Trend column chart: flush outlined columns scaled against the
// member's own best month, with a red trend line through a point centered on
// the top of each column.
function MemberSparkline({ trend, months }) {
  const max = Math.max(...trend, 0);
  if (max <= 0) {
    return <span className="text-xs text-slate-400 italic">No billings in the last six months</span>;
  }
  const COL_W = 48;
  const H = 96;
  const PAD_TOP = 6; // room for the top point's radius
  const W = COL_W * trend.length;
  const points = trend.map((val, i) => {
    const h = val > 0 ? Math.max(((val / max) * (H - PAD_TOP)), 4) : 0;
    return { x: i * COL_W + COL_W / 2, y: H - h, h };
  });
  const polyline = points.map(p => `${p.x},${p.y}`).join(' ');

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block shrink-0" role="img" aria-label="Six-month billed trend">
      {trend.map((val, i) => (
        <g key={months[i] || i}>
          <title>{`${formatMonthShort(months[i])}: ${formatCurrency(val)}`}</title>
          <rect
            x={i * COL_W} y={points[i].y} width={COL_W} height={points[i].h}
            fill={TREND_COLORS.bar} stroke={TREND_COLORS.barBorder} strokeWidth="1.5"
          />
          {/* invisible full-height hit area so hovering empty months still shows the tooltip */}
          <rect x={i * COL_W} y={0} width={COL_W} height={H} fill="transparent" />
        </g>
      ))}
      <polyline points={polyline} fill="none" stroke={TREND_COLORS.line} strokeWidth="2" strokeLinejoin="round" pointerEvents="none" />
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="3.5" fill={TREND_COLORS.point} stroke="#ffffff" strokeWidth="1.5" pointerEvents="none" />
      ))}
    </svg>
  );
}

// Round up to the next multiple of `step` (never below one step so a pod
// with all-zero values still gets a usable gauge range).
function ceilToStep(value, step) {
  const v = Number(value) || 0;
  return Math.max(step, Math.ceil(v / step) * step);
}

// Linear-interpolated quantile of an ascending-sorted array.
function quantileOf(sorted, p) {
  if (sorted.length === 0) return 0;
  const pos = (sorted.length - 1) * p;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

// Quartile zone boundaries [0, Q1, Q2 (median), Q3, max] for a gauge, built
// from the pod dataset so the colored bands reflect where members actually
// fall. Falls back to four equal bands when the data can't be split into
// strictly increasing quartiles (e.g. a one-member pod or many ties).
function quartileBounds(values, max) {
  const sorted = values
    .filter(v => Number.isFinite(v))
    .map(v => Math.min(Math.max(v, 0), max))
    .sort((a, b) => a - b);
  const bounds = [0, quantileOf(sorted, 0.25), quantileOf(sorted, 0.5), quantileOf(sorted, 0.75), max];
  const increasing = bounds.every((b, i) => i === 0 || b > bounds[i - 1]);
  return increasing ? bounds : [0, max * 0.25, max * 0.5, max * 0.75, max];
}

// Pod-wide gauge parameters, computed once per panel so every scorecard in
// the pod shares identical ranges, quartile zones, and average markers.
function computePodGaugeStats(members) {
  const billed = members.map(m => Number(m.billed) || 0);
  const hours = members.map(m => Number(m.hours) || 0);
  const vsMedianPos = members.map(m => m.pct_vs_median).filter(v => v != null && v > 0);
  const avg = arr => (arr.length ? arr.reduce((s, v) => s + v, 0) / arr.length : 0);
  const billedMax = ceilToStep(Math.max(...billed, 0), GAUGE_RANGE_STEPS.billed);
  const hoursMax = ceilToStep(Math.max(...hours, 0), GAUGE_RANGE_STEPS.hours);
  const vsMedianMax = ceilToStep(Math.max(...vsMedianPos, 0), GAUGE_RANGE_STEPS.pctVsMedian);
  return {
    billed: {
      max: billedMax,
      bounds: quartileBounds(billed, billedMax),
      mean: avg(billed),
      median: quantileOf([...billed].sort((a, b) => a - b), 0.5),
    },
    hours: {
      max: hoursMax,
      bounds: quartileBounds(hours, hoursMax),
      mean: avg(hours),
      median: quantileOf([...hours].sort((a, b) => a - b), 0.5),
    },
    pctVsMedian: {
      max: vsMedianMax,
      bounds: quartileBounds(vsMedianPos, vsMedianMax),
    },
  };
}

// Speedometer gauge (SVG): a single semicircular dial split into four
// quartile color zones (Q1→Q4), a needle at the member's value, an optional
// red radial line at `marker` (the pod average), and range labels at both
// ends. The metric figure, label, and caption render beneath the dial; the
// figure turns red when `alert` is true (currently: below the pod median).
function Speedometer({ value, max, bounds, marker, markerLabel, formatValue, formatTick, label, caption, alert, figureText }) {
  const CX = 100, CY = 100;
  const R_BAND = 74, W_BAND = 26;          // zone band center radius / thickness
  const R_OUTER = R_BAND + W_BAND / 2;     // 87
  const NEEDLE_LEN = 82;
  const safeMax = max > 0 ? max : 1;
  const frac = v => Math.min(Math.max((Number(v) || 0) / safeMax, 0), 1);
  const pt = (r, f) => {
    const theta = Math.PI * (1 - f);
    return [CX + r * Math.cos(theta), CY - r * Math.sin(theta)];
  };
  // Semicircle: no arc exceeds 180°, so large-arc is always 0; sweep=1 traces
  // clockwise (left → over the top → right) in SVG coordinates.
  const arc = (r, f0, f1) => {
    if (f1 - f0 <= 0.0005) return '';
    const [x0, y0] = pt(r, f0);
    const [x1, y1] = pt(r, f1);
    return `M ${x0} ${y0} A ${r} ${r} 0 0 1 ${x1} ${y1}`;
  };

  const zoneFracs = (bounds || [0, 0.25, 0.5, 0.75, 1].map(f => f * safeMax)).map(frac);
  const tick = formatTick || formatValue;

  const vFrac = frac(value);
  const [nx, ny] = pt(NEEDLE_LEN, vFrac);
  const needleTheta = Math.PI * (1 - vFrac);
  // Perpendicular offset for the needle's base so it tapers to the tip.
  const bx = 3.5 * Math.sin(needleTheta);
  const by = 3.5 * Math.cos(needleTheta);

  const mFrac = marker != null ? frac(marker) : null;
  const [mx0, my0] = mFrac != null ? pt(R_BAND - W_BAND / 2 - 3, mFrac) : [0, 0];
  const [mx1, my1] = mFrac != null ? pt(R_OUTER + 3, mFrac) : [0, 0];

  return (
    <div className="flex flex-col items-center min-w-0">
      <svg width="200" height="122" viewBox="0 0 200 122" className="block" role="img" aria-label={`${label}: ${formatValue(value)}`}>
        {/* Quartile zones */}
        {GAUGE_COLORS.zones.map((color, i) => {
          const f0 = zoneFracs[i];
          const f1 = zoneFracs[i + 1];
          if (f1 - f0 <= 0.0005) return null;
          const [lx, ly] = pt(R_BAND, (f0 + f1) / 2);
          return (
            <g key={i}>
              <path d={arc(R_BAND, f0, f1)} fill="none" stroke={color} strokeWidth={W_BAND}>
                <title>{`Q${i + 1}: ${tick(bounds ? bounds[i] : f0 * safeMax)} – ${tick(bounds ? bounds[i + 1] : f1 * safeMax)}`}</title>
              </path>
              {f1 - f0 >= 0.07 && (
                <text x={lx} y={ly} fontSize="9" fontWeight="700" fill={GAUGE_COLORS.zoneLabel} textAnchor="middle" dominantBaseline="central" pointerEvents="none">
                  {`Q${i + 1}`}
                </text>
              )}
            </g>
          );
        })}
        {/* Pod average marker */}
        {mFrac != null && (
          <line x1={mx0} y1={my0} x2={mx1} y2={my1} stroke={GAUGE_COLORS.meanLine} strokeWidth="2.5" strokeLinecap="round">
            <title>{`${markerLabel || 'Pod average'}: ${formatValue(marker)}`}</title>
          </line>
        )}
        {/* Needle */}
        <polygon
          points={`${CX + bx},${CY + by} ${CX - bx},${CY - by} ${nx},${ny}`}
          fill={GAUGE_COLORS.needle}
          pointerEvents="none"
        />
        <circle cx={CX} cy={CY} r="5.5" fill={GAUGE_COLORS.needle} />
        <circle cx={CX} cy={CY} r="2" fill="#ffffff" />
        {/* Range labels */}
        <text x={CX - R_BAND} y={CY + 16} fontSize="9" fill={GAUGE_COLORS.tick} textAnchor="middle">{tick(0)}</text>
        <text x={CX + R_BAND} y={CY + 16} fontSize="9" fill={GAUGE_COLORS.tick} textAnchor="middle">{tick(max)}</text>
      </svg>
      <div
        className="text-xl font-bold leading-tight mt-1 text-center"
        style={{ color: alert ? GAUGE_COLORS.figureAlert : GAUGE_COLORS.figure }}
      >
        {figureText ?? formatValue(value)}
      </div>
      <div className="text-xs font-semibold text-slate-800 text-center leading-tight mt-0.5">{label}</div>
      {caption && <div className="text-[11px] text-slate-500 text-center leading-tight">{caption}</div>}
    </div>
  );
}

const formatPct = v => `${Number(v ?? 0).toFixed(1)}%`;
const formatPctTick = v => `${Math.round(Number(v) || 0)}%`;
const formatCurrencyTick = v => '$' + Number(v || 0).toLocaleString('en-US', { maximumFractionDigits: 0 });
const formatHoursTick = v => `${Math.round(Number(v) || 0)}h`;

// Small figure-only card for the scorecard's secondary metrics.
function MetricCard({ value, label, tooltip }) {
  return (
    <div
      className="bg-blue-50 border border-slate-400 rounded-md px-3 py-2.5 text-center min-w-[120px]"
      title={tooltip}
    >
      <div className="text-lg font-bold text-slate-800 leading-tight">{value}</div>
      <div className="text-[11px] text-slate-600 leading-tight mt-0.5 flex items-center justify-center gap-1">
        <span>{label}</span>
        {tooltip && <Info size={11} className="text-slate-400 shrink-0" aria-hidden="true" />}
      </div>
    </div>
  );
}

const BILLING_TO_HOURS_TOOLTIP =
  'Billing-to-Hours Index compares the user\'s share of pod billing to their share of pod hours. '
  + '100 = proportional contribution. >100 = greater billing contribution relative to hours. '
  + '<100 = lower billing contribution relative to hours.';
const MATTERS_WORKED_TOOLTIP =
  'Unique matters with recorded Time or Expense activity during the selected reporting period.';

// One member scorecard: name | three speedometer gauges on a single line,
// then the Six-Month Trend chart alongside four figure-only metric cards.
function MemberRow({ member, stats, months }) {
  const vsMedian = member.pct_vs_median;
  const belowMedian = vsMedian != null && vsMedian < 0;
  const bthIndex = member.billing_to_hours_index;
  const perHour = member.billing_per_hour;

  return (
    <div className="py-5 space-y-4">
      {/* Gauges row */}
      <div className="flex gap-4">
        <div className="w-32 shrink-0 flex items-center">
          <span className="text-sm font-bold text-slate-800 break-words">{member.user_name}</span>
        </div>
        <div className="flex-1 min-w-0 grid grid-cols-1 sm:grid-cols-3 gap-6 justify-items-center">
          <Speedometer
            value={member.billed}
            max={stats.billed.max}
            bounds={stats.billed.bounds}
            marker={stats.billed.mean}
            markerLabel="Pod average billed"
            formatValue={formatCurrency}
            formatTick={formatCurrencyTick}
            label="Total Amount Billed"
            caption={`Pod avg ${formatCurrencyTick(stats.billed.mean)}`}
            alert={member.billed < stats.billed.median}
          />
          <Speedometer
            value={member.hours}
            max={stats.hours.max}
            bounds={stats.hours.bounds}
            marker={stats.hours.mean}
            markerLabel="Pod average hours"
            formatValue={v => `${Number(v || 0).toFixed(1)}h`}
            formatTick={formatHoursTick}
            label="Total Hours Billed"
            caption={`Pod avg ${Number(stats.hours.mean).toFixed(1)}h`}
            alert={member.hours < stats.hours.median}
          />
          <Speedometer
            value={vsMedian == null || belowMedian ? 0 : vsMedian}
            max={stats.pctVsMedian.max}
            bounds={stats.pctVsMedian.bounds}
            formatValue={formatPct}
            formatTick={formatPctTick}
            figureText={vsMedian == null ? '—' : formatPct(Math.abs(vsMedian))}
            label={belowMedian ? '% Below Median' : '% Above Median'}
            caption={vsMedian == null ? 'Pod median unavailable' : undefined}
            alert={belowMedian}
          />
        </div>
      </div>

      {/* Trend + secondary metric cards */}
      <div className="flex gap-4">
        <div className="w-32 shrink-0 flex items-center">
          <span className="text-xs font-semibold text-slate-700">Six-Month Trend:</span>
        </div>
        <div className="flex-1 min-w-0 flex flex-wrap items-center gap-x-8 gap-y-4">
          <MemberSparkline trend={member.trend || []} months={months} />
          <div className="flex-1 grid grid-cols-2 xl:grid-cols-4 gap-3 min-w-[260px]">
            <MetricCard value={formatPct(member.pct_of_pod)} label="Pod Billing Contribution" />
            <MetricCard
              value={bthIndex == null ? '—' : bthIndex}
              label="Billing-to-Hours Index"
              tooltip={BILLING_TO_HOURS_TOOLTIP}
            />
            <MetricCard value={member.matters ?? '—'} label="Matters Worked" tooltip={MATTERS_WORKED_TOOLTIP} />
            <MetricCard
              value={perHour == null ? '—' : `${formatCurrencyTick(perHour)}/hr`}
              label="Billing Per Hour"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

// Individual Pod Members KPI Metrics — scrollable card listing a scorecard
// for every member in the current filter scope. The internal scroll (instead
// of growing the page) keeps anything below reachable for long pods.
function IndividualMembersPanel({ metrics, loading }) {
  const members = metrics?.members || [];
  const months = metrics?.months || [];
  const stats = useMemo(() => computePodGaugeStats(members), [members]);

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <h3 className="text-sm font-semibold text-slate-700">Individual Pod Members KPI Metrics</h3>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
          <span className="flex items-center gap-1.5">
            {GAUGE_COLORS.zones.map((c, i) => (
              <span key={i} className="flex items-center gap-0.5">
                <span className="w-3 h-2 rounded-sm inline-block" style={{ backgroundColor: c }} />Q{i + 1}
              </span>
            ))}
            <span className="ml-1">pod quartiles</span>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-0.5 h-3 inline-block" style={{ backgroundColor: GAUGE_COLORS.meanLine }} />
            Pod average
          </span>
          <span className="flex items-center gap-1.5">
            <span className="font-bold" style={{ color: GAUGE_COLORS.figureAlert }}>Red figure</span>
            = below pod median
          </span>
          {members.length > 0 && (
            <span className="text-slate-400">
              {members.length} member{members.length === 1 ? '' : 's'} · sorted by billed amount
            </span>
          )}
        </div>
      </div>
      {loading ? (
        <p className="text-sm text-slate-400 text-center py-8">...</p>
      ) : members.length === 0 ? (
        <p className="text-sm text-slate-400 text-center py-8">No member activity for this selection</p>
      ) : (
        <div className="max-h-[720px] overflow-y-auto pr-3 divide-y divide-slate-200">
          {members.map(m => (
            <MemberRow
              key={m.user_name}
              member={m}
              stats={stats}
              months={months}
            />
          ))}
        </div>
      )}
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
  // Pod filter — value is the Clio group id (as a string; '' = all pods).
  const [podFilter, setPodFilter] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [showTable, setShowTable] = useState(false);

  // Chart granularity controls only the trend chart (not the cards). The
  // chart's date window is auto-sized server-side based on this value:
  //   month -> last 6 months    week -> last 12 weeks    day -> last 30 days
  const [granularity, setGranularity] = useState('month');

  // Employee list for the User dropdown (full firm list)
  const [employees, setEmployees] = useState([]);
  // Pods (Clio Groups) for the Pod/Group dropdown: [{group_id, name, members}]
  const [pods, setPods] = useState([]);

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
    if (podFilter) params.set('group_id', podFilter);
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
    if (podFilter) params.set('group_id', podFilter);
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
    get('/billing/pods').then(r => setPods(r.data || [])).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The User dropdown is dependent on the Pod selection: with a pod chosen it
  // lists only that pod's members (from Clio Groups, already loaded with the
  // pods payload — no extra API call). Clear a stale user selection when it
  // isn't part of the newly selected pod.
  const selectedPod = pods.find(p => String(p.group_id) === podFilter) || null;
  const userOptions = selectedPod ? (selectedPod.members || []) : employees;

  function handlePodChange(value) {
    setPodFilter(value);
    if (value) {
      const pod = pods.find(p => String(p.group_id) === value);
      if (pod && userFilter && !(pod.members || []).includes(userFilter)) {
        setUserFilter('');
      }
    }
  }

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
      // The refresh runs in the background on the server. We get back an
      // immediate "started", then poll for completion.
      // No reconcile_days override → the server reconciles the recent ~35-day
      // window BY ACTIVITY DATE (late-entered items included), which finishes
      // in a few minutes and reliably completes. The deeper ~6-month chart
      // history is refreshed by an occasional explicit backfill, not here.
      await post('/billing/refresh', {});
      setRefreshNote('Syncing recent data from Clio… this usually takes a few minutes. You can keep working.');

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
  const podKpis = summary?.pod_kpis || null;

  // "Viewing:" context label — prefer the server-echoed pod name (reflects
  // what was actually applied) and fall back to the local dropdown state.
  const appliedPodName = summary?.pod_name
    || (selectedPod ? selectedPod.name : null);
  const viewingLabel = appliedPodName
    ? `${appliedPodName} — ${userFilter || 'All Members'}`
    : (userFilter || 'Firm-Wide — All Users');

  // Abbreviated version of the "Timeframe:" label, shown as the title of the
  // Top Category donut tooltips. Tracks the same applied date window (default
  // or user-filtered) the Totals cards use.
  const donutRangeLabel = `${formatShortRangeDate(summary?.card_date_from || dateFrom)} - ${formatShortRangeDate(summary?.card_date_to || dateTo)}`;

  // Pod KPI Metrics section — defined here so it can be positioned below the
  // Top Categories cards: Partners read top-down (high-level first), Team
  // Leads keep scrolling for the pod-level drill-down.
  const podKpiSection = (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Pod KPI Metrics</h2>
        {podKpis?.business_days > 0 && (
          <span className="text-xs text-slate-400">{podKpis.business_days} working days in period</span>
        )}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <PodKpiCard
          icon={Award}
          label="Top Contributor to Pod"
          color="bg-indigo-500"
          loading={loading}
          name={podKpis?.top_contributor?.user_name}
          figure={podKpis?.top_contributor ? `${podKpis.top_contributor.pct_of_pod}% of Pod Billings` : ''}
          subtitle={podKpis?.top_contributor
            ? `${formatCurrency(podKpis.top_contributor.amount)} of ${formatCurrency(podKpis.pod_total)} total`
            : ''}
          info={{
            title: 'Top Contributor to Pod Metric',
            description: 'Ratio calculates the proportion of Billed Amount that a single team member generates compared to the entire Pod\u2019s Billed Amount.',
            calculation: 'Top Contributor to Pod = Team Member Billed Amount \u00F7 Pod Billed Amount \u00D7 100',
          }}
        />
        <PodKpiCard
          icon={CalendarDays}
          label="Most Entries per Working Day"
          color="bg-teal-500"
          loading={loading}
          name={podKpis?.most_entries_per_day?.user_name}
          figure={podKpis?.most_entries_per_day ? `${podKpis.most_entries_per_day.per_day} Entries / Day` : ''}
          subtitle={podKpis?.most_entries_per_day
            ? `${podKpis.most_entries_per_day.entries.toLocaleString()} entries over ${podKpis.business_days} working days`
            : ''}
          info={{
            title: 'Most Entries per Working Day Metric',
            description: 'Identifies the team member logging the highest average number of activity entries per business day (Mon\u2013Fri) in the selected period.',
            calculation: 'Entries per Working Day = Number of Entries \u00F7 Number of Business Days in Selected Period',
          }}
        />
        <PodKpiCard
          icon={Timer}
          label="Top Billed per Hour"
          color="bg-rose-500"
          loading={loading}
          name={podKpis?.top_billed_per_hour?.user_name}
          figure={podKpis?.top_billed_per_hour ? `${formatCurrency(podKpis.top_billed_per_hour.rate)} / Hour` : ''}
          subtitle={podKpis?.top_billed_per_hour
            ? `${formatCurrency(podKpis.top_billed_per_hour.billed)} over ${formatHours(podKpis.top_billed_per_hour.hours)}`
            : ''}
          info={{
            title: 'Top Billed per Hour Metric',
            description: 'Identifies the team member generating the highest effective billing rate \u2014 total dollars billed relative to total hours logged in the selected period.',
            calculation: 'Billed per Hour = Total Billed Amount \u00F7 Total Hours Logged',
          }}
        />
      </div>
    </div>
  );

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
          <form onSubmit={handleApplyFilters} className="px-5 pb-4 grid grid-cols-1 md:grid-cols-5 gap-4 border-t border-slate-100 pt-4">
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
              <label className="block text-xs font-medium text-slate-500 mb-1">Pod / Group</label>
              <select value={podFilter} onChange={e => handlePodChange(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">All Pods / Groups</option>
                {pods.map(pod => (
                  <option key={pod.group_id} value={String(pod.group_id)}>{pod.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">User</label>
              <select value={userFilter} onChange={e => setUserFilter(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">{selectedPod ? `All ${selectedPod.name} Members` : 'All Users'}</option>
                {userOptions.map(name => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">Entry Type</label>
              <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">All</option>
                <option value="TimeEntry">Time</option>
                <option value="ExpenseEntry">Expense</option>
              </select>
            </div>
            <div className="md:col-span-5 flex justify-end">
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

      {/* KPI Cards — labelled with the active filter scope + date window so
          executives always know exactly what the numbers cover. */}
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Totals</h2>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
            <span className="text-slate-600">
              <span className="font-semibold text-slate-800">Viewing:</span>{' '}
              {viewingLabel}
            </span>
            <span className="text-slate-600">
              <span className="font-semibold text-slate-800">Timeframe:</span>{' '}
              {formatLongDate(summary?.card_date_from || dateFrom)} through {formatLongDate(summary?.card_date_to || dateTo)}
            </span>
          </div>
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
            <CategoryDonut
              data={byCategoryTime}
              colors={TIME_DONUT_COLORS}
              rangeLabel={donutRangeLabel}
              emptyMessage="No time entries in this period"
            />
          </div>

          {/* Expense categories */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-slate-700">Top Expense Categories</h3>
              <span className="text-xs text-slate-400">Expense Category</span>
            </div>
            <CategoryDonut
              data={byCategoryExpense}
              colors={EXPENSE_DONUT_COLORS}
              rangeLabel={donutRangeLabel}
              emptyMessage="No expense entries in this period"
            />
          </div>
        </div>
      )}

      {/* ── Pod drill-down zone ──────────────────────────────────────────
          Everything above is the Partners' high-level view; from here down
          is the Team Lead granular view: pod leaderboard cards, then the
          per-member metrics panel. */}
      {!loading && podKpiSection}

      {!loading && (
        <IndividualMembersPanel metrics={summary?.member_metrics} loading={loading} />
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
                      <td className="px-4 py-2 text-right text-slate-700">{a.price != null ? `$${Number(a.price).toFixed(2)}` : '—'}</td>
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
