/**
 * KpiCard — the standard metric card used on every dashboard page.
 *
 * Label top-left, colored icon badge top-right, big figure, optional
 * subtitle. Light + dark mode styling lives here so all dashboards match.
 */
export default function KpiCard({ icon: Icon, label, value, subtitle, color, loading }) {
  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl p-5 shadow-sm border border-slate-200 dark:border-slate-700">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</span>
        {Icon && (
          <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${color}`}>
            <Icon size={18} className="text-white" />
          </div>
        )}
      </div>
      <div className="text-2xl font-bold text-slate-800 dark:text-slate-100">
        {loading ? '...' : value}
      </div>
      {subtitle && <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">{subtitle}</p>}
    </div>
  );
}
