/**
 * Custom Fields page — advanced search + results table + detail drill-down.
 *
 * Layout mirrors the Matters page:
 *   Top:     Search bar (Field ID / Name, field_type dropdown, parent_type filter)
 *   Bottom:  Results table with click-to-expand detail panel
 */

import { useState, useEffect, Fragment } from 'react';
import { get } from '../api/client';
import {
  Search,
  ChevronDown,
  ChevronUp,
  X,
  Loader2,
  ListChecks,
  Tag,
} from 'lucide-react';

// ─── Small shared components ───────────────────────────────────────────────

function FieldLabel({ children, htmlFor }) {
  return <label htmlFor={htmlFor} className="block text-xs font-medium text-slate-500 mb-1">{children}</label>;
}

function TypeBadge({ type }) {
  const colors = {
    text_line: 'bg-blue-50 text-blue-700',
    picklist: 'bg-violet-50 text-violet-700',
    numeric: 'bg-emerald-50 text-emerald-700',
    date: 'bg-amber-50 text-amber-700',
    checkbox: 'bg-pink-50 text-pink-700',
    text_area: 'bg-cyan-50 text-cyan-700',
    url: 'bg-orange-50 text-orange-700',
    email: 'bg-teal-50 text-teal-700',
    currency: 'bg-green-50 text-green-700',
    matter: 'bg-indigo-50 text-indigo-700',
    contact: 'bg-rose-50 text-rose-700',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${colors[type] || 'bg-slate-100 text-slate-600'}`}>
      {type || '—'}
    </span>
  );
}

function BoolBadge({ value, trueLabel = 'Yes', falseLabel = 'No' }) {
  if (value == null) return <span className="text-slate-400">—</span>;
  return value
    ? <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">{trueLabel}</span>
    : <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">{falseLabel}</span>;
}

// ─── Detail panel for a single custom field ────────────────────────────────

function FieldDetail({ field, onClose }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    get(`/custom-fields/${field.id}`)
      .then(res => {
        if (cancelled) return;
        const d = res?.data || res;
        setDetail(typeof d === 'object' && !Array.isArray(d) ? d : {});
      })
      .catch(err => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [field.id]);

  if (loading) {
    return (
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-6 mt-2 mb-2">
        <div className="flex items-center gap-2 text-blue-600 text-sm"><Loader2 size={16} className="animate-spin" /> Loading field detail...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-xl p-6 mt-2 mb-2">
        <p className="text-sm text-red-600">{error}</p>
      </div>
    );
  }

  const d = detail || {};
  const picklistOptions = d.picklist_options || [];

  return (
    <div className="bg-slate-50 border border-slate-200 rounded-xl p-6 mt-2 mb-2">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold text-slate-800">{d.name || field.name} — Full Detail</h3>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><X size={18} /></button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm">
        {/* Identity */}
        <div className="space-y-3">
          <h4 className="font-semibold text-slate-700 flex items-center gap-1.5"><Tag size={14} /> Identity</h4>
          <InfoRow label="Field ID" value={d.id} alwaysShow />
          <InfoRow label="Name" value={d.name} alwaysShow />
          <InfoRow label="Created" value={formatDate(d.created_at)} alwaysShow />
          <InfoRow label="Updated" value={formatDate(d.updated_at)} alwaysShow />
        </div>

        {/* Configuration */}
        <div className="space-y-3">
          <h4 className="font-semibold text-slate-700 flex items-center gap-1.5"><ListChecks size={14} /> Configuration</h4>
          <DetailBadgeRow label="Type"><TypeBadge type={d.field_type} /></DetailBadgeRow>
          <InfoRow label="Parent Type" value={d.parent_type} alwaysShow />
          <DetailBadgeRow label="Required"><BoolBadge value={d.required} /></DetailBadgeRow>
          <DetailBadgeRow label="Displayed"><BoolBadge value={d.displayed} /></DetailBadgeRow>
          <DetailBadgeRow label="Deleted"><BoolBadge value={d.deleted} trueLabel="Deleted" falseLabel="Active" /></DetailBadgeRow>
        </div>

        {/* Field set (from custom_field_sets API, merged on the server) */}
        <div className="space-y-3 md:col-span-3">
          <h4 className="font-semibold text-slate-700">Field Set</h4>
          {d.field_set?.name ? (
            <div className="space-y-2">
              <InfoRow label="Set ID" value={d.field_set.id} alwaysShow />
              <InfoRow label="Set Name" value={d.field_set.name} alwaysShow />
              <InfoRow label="Set Parent Type" value={d.field_set.parent_type} alwaysShow />
              {(d.field_set.custom_fields?.length ?? 0) > 0 && (
                <div className="mt-3 bg-white rounded-lg border border-slate-200 overflow-hidden">
                  <p className="text-xs text-slate-500 px-3 py-2 bg-slate-50 border-b border-slate-200">
                    Fields in this set (current field highlighted)
                  </p>
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 border-b border-slate-200">
                      <tr>
                        <th className="text-left px-3 py-2 font-medium text-slate-600">ID</th>
                        <th className="text-left px-3 py-2 font-medium text-slate-600">Name</th>
                        <th className="text-left px-3 py-2 font-medium text-slate-600">Type</th>
                        <th className="text-left px-3 py-2 font-medium text-slate-600">Required</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(d.field_set.custom_fields || []).map(cf => (
                        <tr
                          key={cf.id}
                          className={`border-b border-slate-100 ${cf.id === d.id ? 'bg-blue-50' : ''}`}
                        >
                          <td className="px-3 py-2 text-slate-600 whitespace-nowrap">{cf.id}</td>
                          <td className="px-3 py-2 font-medium text-slate-800">{cf.name}</td>
                          <td className="px-3 py-2"><TypeBadge type={cf.field_type} /></td>
                          <td className="px-3 py-2"><BoolBadge value={cf.required} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ) : (
            <p className="text-slate-400 text-xs italic">Not part of a custom field set (or set list could not be loaded).</p>
          )}
        </div>
      </div>

      {/* Picklist Options */}
      {picklistOptions.length > 0 && (
        <div className="mt-6">
          <h4 className="font-semibold text-slate-700 mb-3">Picklist Options ({picklistOptions.length})</h4>
          <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="text-left px-4 py-2 font-medium text-slate-600">ID</th>
                  <th className="text-left px-4 py-2 font-medium text-slate-600">Option</th>
                  <th className="text-left px-4 py-2 font-medium text-slate-600">Status</th>
                </tr>
              </thead>
              <tbody>
                {picklistOptions.map(opt => (
                  <tr key={opt.id} className="border-b border-slate-100">
                    <td className="px-4 py-2 text-slate-600">{opt.id}</td>
                    <td className="px-4 py-2 font-medium text-slate-800">{opt.option}</td>
                    <td className="px-4 py-2">
                      {opt.deleted
                        ? <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full">Deleted</span>
                        : <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">Active</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/** Label + text value for custom field detail. Bold labels: edit rows in `FieldDetail` above. */
function InfoRow({ label, value, alwaysShow = false }) {
  const missing = value == null || value === '';
  if (missing && !alwaysShow) return null;
  const text = missing ? '—' : String(value);
  return (
    <div className="flex justify-between gap-2 items-baseline">
      <span className="text-slate-800 font-semibold shrink-0">{label}</span>
      <span className={`text-slate-600 text-right font-normal truncate max-w-[60%] ${missing ? 'italic text-slate-400' : ''}`}>{text}</span>
    </div>
  );
}

/** Label + badge (or any right-side control); matches `InfoRow` label weight. */
function DetailBadgeRow({ label, children }) {
  return (
    <div className="flex justify-between gap-2 items-center">
      <span className="text-slate-800 font-semibold shrink-0">{label}</span>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function formatDate(dateStr) {
  if (!dateStr) return null;
  try { return new Date(dateStr).toLocaleDateString(); } catch { return dateStr; }
}

// ─── Main page ─────────────────────────────────────────────────────────────

export default function CustomFieldsPage() {
  const [query, setQuery] = useState('');
  const [fieldType, setFieldType] = useState('');
  const [parentType, setParentType] = useState('Matter');
  const [fields, setFields] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  async function handleSearch(e) {
    if (e) e.preventDefault();
    setLoading(true);
    setSearched(true);
    setExpandedId(null);

    const params = new URLSearchParams();
    if (query.trim()) params.set('q', query.trim());
    if (fieldType) params.set('field_type', fieldType);
    if (parentType) params.set('parent_type', parentType);
    params.set('limit', '50');

    try {
      const res = await get(`/custom-fields/search?${params.toString()}`);
      console.debug('[CustomFields] Search response', res);
      setFields(res.data || []);
    } catch (err) {
      console.error('[CustomFields] Search error', err);
      setFields([]);
    } finally {
      setLoading(false);
    }
  }

  function clearFilters() {
    setQuery('');
    setFieldType('');
    setParentType('Matter');
    setFields([]);
    setSearched(false);
    setExpandedId(null);
  }

  const FIELD_TYPES = [
    '', 'text_line', 'text_area', 'numeric', 'currency', 'date',
    'picklist', 'checkbox', 'url', 'email', 'matter', 'contact',
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Custom Fields</h1>

      {/* ── Search Panel ──────────────────────────────────────────────── */}
      <form onSubmit={handleSearch} className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-6">
        <div className="flex gap-3 items-end">
          <div className="flex-[2] min-w-0">
            <FieldLabel htmlFor="cf-query">Field ID / Name</FieldLabel>
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                id="cf-query"
                type="text"
                placeholder="e.g. Vehicle Year or 21836420"
                value={query}
                onChange={e => setQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            </div>
          </div>
          <div className="flex-1 min-w-0">
            <FieldLabel htmlFor="cf-type">Field Type</FieldLabel>
            <select
              id="cf-type"
              value={fieldType}
              onChange={e => setFieldType(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
            >
              {FIELD_TYPES.map(t => (
                <option key={t} value={t}>{t || 'All types'}</option>
              ))}
            </select>
          </div>
          <div className="flex-1 min-w-0">
            <FieldLabel htmlFor="cf-parent">Parent Type</FieldLabel>
            <select
              id="cf-parent"
              value={parentType}
              onChange={e => setParentType(e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
            >
              <option value="">All</option>
              <option value="Matter">Matter</option>
              <option value="Contact">Contact</option>
              <option value="Activity">Activity</option>
            </select>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="inline-flex items-center gap-2 px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50 shrink-0"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
            Search
          </button>
        </div>

        {(query || fieldType) && (
          <button type="button" onClick={clearFilters} className="text-xs text-slate-400 hover:text-red-500 mt-3">
            Clear filters
          </button>
        )}
      </form>

      {/* ── Results Table ─────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-800">
            {searched ? `${fields.length} Result${fields.length !== 1 ? 's' : ''}` : 'Custom Fields'}
          </h2>
          {!searched && (
            <span className="text-xs text-slate-400">Use the search above to find custom fields</span>
          )}
        </div>

        {loading ? (
          <div className="px-5 py-8 text-center">
            <Loader2 size={24} className="animate-spin text-blue-500 mx-auto mb-2" />
            <p className="text-sm text-slate-400">Searching Clio...</p>
          </div>
        ) : !searched ? (
          <div className="px-5 py-8 text-center">
            <ListChecks size={32} className="mx-auto text-slate-200 mb-3" />
            <p className="text-sm text-slate-400">Enter a search query above to find custom fields.</p>
          </div>
        ) : fields.length === 0 ? (
          <div className="px-5 py-8 text-center">
            <p className="text-sm text-slate-400">No custom fields matched your search criteria.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="text-left px-5 py-3 font-medium text-slate-600 w-8"></th>
                <th className="text-left px-5 py-3 font-medium text-slate-600">ID</th>
                <th className="text-left px-5 py-3 font-medium text-slate-600">Name</th>
                <th className="text-left px-5 py-3 font-medium text-slate-600">Type</th>
                <th className="text-left px-5 py-3 font-medium text-slate-600">Parent</th>
                <th className="text-left px-5 py-3 font-medium text-slate-600">Required</th>
                <th className="text-left px-5 py-3 font-medium text-slate-600">Displayed</th>
              </tr>
            </thead>
            <tbody>
              {fields.map(f => {
                const isExpanded = expandedId === f.id;
                const req = f.required === true || f.required === 'true';
                const disp = f.displayed === true || f.displayed === 'true';
                return (
                  <Fragment key={f.id}>
                    <tr
                      className="border-b border-slate-100 group cursor-pointer hover:bg-blue-50/80 transition"
                      onClick={() => setExpandedId(isExpanded ? null : f.id)}
                    >
                      <td className="px-5 py-3 w-8 align-middle">
                        {isExpanded ? <ChevronUp size={16} className="text-blue-500" /> : <ChevronDown size={16} className="text-slate-400 group-hover:text-blue-500" />}
                      </td>
                      <td className="px-5 py-3 text-slate-600 whitespace-nowrap align-middle">{f.id}</td>
                      <td className="px-5 py-3 font-medium text-slate-800 max-w-md align-middle">
                        <span className="block truncate" title={f.name || ''}>{f.name}</span>
                      </td>
                      <td className="px-5 py-3 align-middle"><TypeBadge type={f.field_type} /></td>
                      <td className="px-5 py-3 text-slate-600 whitespace-nowrap align-middle">{f.parent_type ?? '—'}</td>
                      <td className="px-5 py-3 align-middle"><BoolBadge value={req} /></td>
                      <td className="px-5 py-3 align-middle"><BoolBadge value={disp} /></td>
                    </tr>
                    {isExpanded && (
                      <tr className="bg-slate-50/60 border-b border-slate-100">
                        <td colSpan={7} className="px-5 pb-4 pt-2">
                          <FieldDetail field={f} onClose={() => setExpandedId(null)} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
