import { useState, useEffect } from 'react';
import { get } from '../api/client';

export default function CustomFieldsPage() {
  const [fields, setFields] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    get('/custom-fields?parent_type=Matter&limit=50')
      .then(r => setFields(r.data || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Custom Fields (Matter)</h1>

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr>
              <th className="text-left px-5 py-3 font-medium text-slate-600">Field ID</th>
              <th className="text-left px-5 py-3 font-medium text-slate-600">Name</th>
              <th className="text-left px-5 py-3 font-medium text-slate-600">Type</th>
              <th className="text-left px-5 py-3 font-medium text-slate-600">Parent</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={4} className="px-5 py-4 text-slate-400">Loading...</td></tr>
            ) : fields.map(f => (
              <tr key={f.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="px-5 py-3 text-slate-600">{f.id}</td>
                <td className="px-5 py-3 font-medium text-slate-800">{f.name}</td>
                <td className="px-5 py-3">
                  <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
                    {f.field_type}
                  </span>
                </td>
                <td className="px-5 py-3 text-slate-600">{f.parent_type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
