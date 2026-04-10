/**
 * Dashboard — landing page after login.
 *
 * Shows:
 *   - KPI metric cards (total matters, custom fields, recent operations)
 *   - Mini audit log (recent activity feed)
 */

import { useState, useEffect } from 'react';
import { get } from '../api/client';
import { FileText, ListChecks, ClipboardList, Clock } from 'lucide-react';

function KpiCard({ icon: Icon, label, value, color, loading }) {
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
    </div>
  );
}

function AuditEntry({ entry }) {
  const time = new Date(entry.timestamp).toLocaleString();
  return (
    <div className="flex items-start gap-3 py-3 border-b border-slate-100 last:border-0">
      <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center shrink-0 mt-0.5">
        <ClipboardList size={14} className="text-blue-600" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-slate-800">
          <span className="font-medium">{entry.username}</span>
          {' '}performed{' '}
          <span className="font-medium text-blue-600">{entry.action}</span>
        </p>
        {entry.matter_id && (
          <p className="text-xs text-slate-500 mt-0.5">
            Matter: {entry.matter_id}
            {entry.field_name && ` · Field: ${entry.field_name}`}
          </p>
        )}
        <p className="text-xs text-slate-400 mt-0.5">{time}</p>
      </div>
      <span className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${
        entry.status === 'success'
          ? 'bg-green-100 text-green-700'
          : 'bg-red-100 text-red-700'
      }`}>
        {entry.status}
      </span>
    </div>
  );
}

export default function DashboardPage() {
  const [mattersCount, setMattersCount] = useState(null);
  const [fieldsCount, setFieldsCount] = useState(null);
  const [auditEntries, setAuditEntries] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      get('/matters?limit=1').then(r => r.meta?.paging?.total || r.data?.length || 0),
      get('/custom-fields?parent_type=Matter&limit=1').then(r => r.meta?.paging?.total || r.data?.length || 0),
      get('/audit?limit=10').then(r => r.data || []),
    ])
      .then(([matters, fields, audit]) => {
        setMattersCount(matters);
        setFieldsCount(fields);
        setAuditEntries(audit);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Dashboard</h1>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5 mb-8">
        <KpiCard
          icon={FileText}
          label="Total Matters"
          value={mattersCount}
          color="bg-blue-500"
          loading={loading}
        />
        <KpiCard
          icon={ListChecks}
          label="Custom Fields"
          value={fieldsCount}
          color="bg-teal-500"
          loading={loading}
        />
        <KpiCard
          icon={Clock}
          label="Recent Operations"
          value={auditEntries.length}
          color="bg-violet-500"
          loading={loading}
        />
      </div>

      {/* Recent Activity */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200">
        <div className="px-5 py-4 border-b border-slate-200">
          <h2 className="text-lg font-semibold text-slate-800">Recent Activity</h2>
        </div>
        <div className="px-5 py-2">
          {loading ? (
            <p className="text-sm text-slate-400 py-4">Loading...</p>
          ) : auditEntries.length === 0 ? (
            <p className="text-sm text-slate-400 py-4">No operations recorded yet.</p>
          ) : (
            auditEntries.map((entry) => (
              <AuditEntry key={entry.id} entry={entry} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
