/**
 * Matters page — list, search, and view matter details.
 * Placeholder: will be fully built in a subsequent phase.
 */

import { useState, useEffect } from 'react';
import { get } from '../api/client';

export default function MattersPage() {
  const [matters, setMatters] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    get('/matters?limit=20')
      .then(r => setMatters(r.data || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Matters</h1>

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="text-left px-5 py-3 font-medium text-slate-600">Matter ID</th>
              <th className="text-left px-5 py-3 font-medium text-slate-600">Display Number</th>
              <th className="text-left px-5 py-3 font-medium text-slate-600">Description</th>
              <th className="text-left px-5 py-3 font-medium text-slate-600">Status</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={4} className="px-5 py-4 text-slate-400">Loading...</td></tr>
            ) : matters.map(m => (
              <tr key={m.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-5 py-3 text-slate-600">{m.id}</td>
                <td className="px-5 py-3 font-medium text-slate-800">{m.display_number}</td>
                <td className="px-5 py-3 text-slate-600">{m.description}</td>
                <td className="px-5 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    m.status === 'Open' ? 'bg-green-100 text-green-700' :
                    m.status === 'Closed' ? 'bg-slate-100 text-slate-600' :
                    'bg-yellow-100 text-yellow-700'
                  }`}>
                    {m.status}
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
