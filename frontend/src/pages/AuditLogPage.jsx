import { useState, useEffect } from 'react';
import { get } from '../api/client';

export default function AuditLogPage() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    get('/audit?limit=100')
      .then(r => setEntries(r.data || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Audit Log</h1>

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-slate-600">Timestamp</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">User</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">Action</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">Matter</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">Field</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">Before</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">After</th>
              <th className="text-left px-4 py-3 font-medium text-slate-600">Status</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="px-4 py-4 text-slate-400">Loading...</td></tr>
            ) : entries.length === 0 ? (
              <tr><td colSpan={8} className="px-4 py-4 text-slate-400">No audit entries yet.</td></tr>
            ) : entries.map(e => (
              <tr key={e.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">
                  {new Date(e.timestamp).toLocaleString()}
                </td>
                <td className="px-4 py-3 font-medium text-slate-800">{e.username}</td>
                <td className="px-4 py-3">
                  <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
                    {e.action}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-600">{e.matter_id || '—'}</td>
                <td className="px-4 py-3 text-slate-600">{e.field_name || '—'}</td>
                <td className="px-4 py-3 text-slate-500 text-xs">{e.before_value || '—'}</td>
                <td className="px-4 py-3 text-slate-500 text-xs">{e.after_value || '—'}</td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    e.status === 'success' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                  }`}>
                    {e.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
