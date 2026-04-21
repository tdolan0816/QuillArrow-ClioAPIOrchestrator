/**
 * Matters page — advanced search + results table + detail drill-down.
 *
 * Layout (matching stakeholder mockup):
 *   Top section:  Search bar row (Matter ID/Display #, Open Date, Responsible Attorney, Search btn)
 *                 Advanced Search row (Originating Attorney, Responsible Staff, custom field filters)
 *   Bottom:       Results table with click-to-expand detail panel
 */

import { useState, useEffect, Fragment } from 'react';
import { get } from '../api/client';
import {
  Search,
  ChevronDown,
  ChevronUp,
  X,
  Loader2,
  User,
  Calendar,
  Scale,
  DollarSign,
  Tag,
  Users,
  Briefcase,
} from 'lucide-react';

// ─── Shared small components ───────────────────────────────────────────────

function SearchInput({ id, placeholder, value, onChange, icon: Icon }) {
  return (
    <div className="relative flex-1 min-w-0">
      {Icon && <Icon size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />}
      <input
        id={id}
        type="text"
        placeholder={placeholder}
        value={value}
        onChange={e => onChange(e.target.value)}
        className={`w-full ${Icon ? 'pl-9' : 'pl-3'} pr-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500`}
      />
    </div>
  );
}

function DateInput({ id, value, onChange, placeholder }) {
  return (
    <input
      id={id}
      type="date"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
    />
  );
}

function FieldLabel({ children, htmlFor }) {
  return <label htmlFor={htmlFor} className="block text-xs font-medium text-slate-500 mb-1">{children}</label>;
}

function StatusBadge({ status }) {
  const cls = status === 'Open' ? 'bg-green-100 text-green-700'
    : status === 'Closed' ? 'bg-slate-100 text-slate-600'
    : 'bg-yellow-100 text-yellow-700';
  return <span className={`text-xs px-2 py-0.5 rounded-full ${cls}`}>{status}</span>;
}

// ─── Detail panel for a single matter ──────────────────────────────────────

function MatterDetail({ matter, onClose }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    get(`/matters/${matter.id}`)
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
  }, [matter.id]);

  if (loading) {
    return (
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-6 mt-2 mb-2">
        <div className="flex items-center gap-2 text-blue-600 text-sm"><Loader2 size={16} className="animate-spin" /> Loading matter detail...</div>
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
  const cfvs = d.custom_field_values || [];

  return (
    <div className="bg-slate-50 border border-slate-200 rounded-xl p-6 mt-2 mb-2 animate-in">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold text-slate-800">
          {d.display_number || matter.display_number} — Full Detail
        </h3>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><X size={18} /></button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm">
        {/* Identity & Status */}
        <div className="space-y-3">
          <h4 className="font-semibold text-slate-700 flex items-center gap-1.5"><Briefcase size={14} /> Identity & Status</h4>
          <InfoRow label="Matter ID" value={d.id} alwaysShow />
          <InfoRow label="Display Number" value={d.display_number} alwaysShow />
          <InfoRow label="Description" value={d.description} alwaysShow />
          <InfoRow label="Status" value={d.status} alwaysShow />
          <InfoRow label="Created" value={formatDate(d.created_at)} alwaysShow />
          <InfoRow label="Updated" value={formatDate(d.updated_at)} alwaysShow />
        </div>

        {/* Dates & Details */}
        <div className="space-y-3">
          <h4 className="font-semibold text-slate-700 flex items-center gap-1.5"><Calendar size={14} /> Dates & Details</h4>
          <InfoRow label="Open Date" value={d.open_date} alwaysShow />
          <InfoRow label="Close Date" value={d.close_date} />
          <InfoRow label="Pending Date" value={d.pending_date} alwaysShow />
          <InfoRow label="Practice Area" value={d.practice_area?.name ?? d.practice_area} alwaysShow />
          <InfoRow label="Location" value={d.location} alwaysShow />
          <InfoRow label="Client Reference" value={d.client_reference} alwaysShow />
          <InfoRow label="Billable" value={d.billable != null ? (d.billable ? 'Yes' : 'No') : null} alwaysShow />
          <InfoRow label="Billing Method" value={d.billing_method} alwaysShow />
          <InfoRow label="Stage" value={d.matter_stage?.name} />
          <InfoRow label="Group" value={d.group?.name} alwaysShow />
        </div>

        {/* People & Financials */}
        <div className="space-y-3">
          <h4 className="font-semibold text-slate-700 flex items-center gap-1.5"><Users size={14} /> People</h4>
          <InfoRow label="Client" value={d.client?.name ?? d.client} alwaysShow />
          <InfoRow label="Responsible Attorney" value={d.responsible_attorney?.name ?? d.responsible_attorney} alwaysShow />
          <InfoRow label="Originating Attorney" value={d.originating_attorney?.name ?? d.originating_attorney} alwaysShow />
          <InfoRow label="Responsible Staff" value={d.responsible_staff?.name ?? d.responsible_staff} alwaysShow />

          {d.account_balances && d.account_balances.length > 0 && (
            <>
              <h4 className="font-semibold text-slate-700 flex items-center gap-1.5 pt-2"><DollarSign size={14} /> Financials</h4>
              {d.account_balances.map((ab, i) => (
                <InfoRow key={i} label={ab.type || `Balance ${i + 1}`} value={ab.balance != null ? `$${Number(ab.balance).toLocaleString()}` : null} />
              ))}
            </>
          )}
        </div>
      </div>

      {/* Custom Field Values */}
      {cfvs.length > 0 && (
        <div className="mt-6">
          <h4 className="font-semibold text-slate-700 flex items-center gap-1.5 mb-3"><Tag size={14} /> Custom Fields ({cfvs.length})</h4>
          <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="text-left px-4 py-2 font-medium text-slate-600">Field Name</th>
                  <th className="text-left px-4 py-2 font-medium text-slate-600">Value</th>
                  <th className="text-left px-4 py-2 font-medium text-slate-600">Type</th>
                </tr>
              </thead>
              <tbody>
                {cfvs.map((cfv, i) => (
                  <tr key={cfv.value_id || i} className="border-b border-slate-100">
                    <td className="px-4 py-2 font-medium text-slate-800">{cfv.custom_field?.name || cfv.custom_field?.field_def_id || '—'}</td>
                    <td className="px-4 py-2 text-slate-700">{cfv.value != null ? String(cfv.value) : <span className="text-slate-400 italic">empty</span>}</td>
                    <td className="px-4 py-2">
                      <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">
                        {cfv.custom_field?.field_type || '—'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Relationships */}
      {d.relationships && d.relationships.length > 0 && (
        <div className="mt-6">
          <h4 className="font-semibold text-slate-700 flex items-center gap-1.5 mb-3"><User size={14} /> Relationships ({d.relationships.length})</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {d.relationships.map((rel, i) => (
              <div key={rel.id || i} className="bg-white rounded-lg border border-slate-200 px-4 py-2 text-sm">
                <span className="font-medium text-slate-700">{rel.description || 'Relationship'}</span>
                {rel.contact && <span className="text-slate-500 ml-2">— {rel.contact.name || rel.contact.id}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Single-line label + value for Matter detail panels.
 * Labels are semibold; values are regular weight. Edit matter detail rows in `MatterDetail` above.
 */
function displayMatterDetailValue(v) {
  if (v == null || v === '') return '—';
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v);
  if (typeof v === 'object' && v.date != null) return String(v.date);
  if (typeof v === 'object' && v.name != null) return String(v.name);
  if (typeof v === 'object' && v.label != null) return String(v.label);
  return String(v);
}

function InfoRow({ label, value, alwaysShow = false }) {
  const missing = value == null || value === '';
  if (missing && !alwaysShow) return null;
  const text = missing ? '—' : displayMatterDetailValue(value);
  return (
    <div className="flex justify-between gap-2 items-baseline">
      <span className="text-slate-800 font-semibold shrink-0">{label}</span>
      <span className={`text-slate-600 text-right font-normal truncate max-w-[60%] ${missing ? 'italic text-slate-400' : ''}`}>{text}</span>
    </div>
  );
}

function formatDate(dateStr) {
  if (!dateStr) return null;
  try { return new Date(dateStr).toLocaleDateString(); } catch { return dateStr; }
}

/** Clio sometimes returns open_date as a string or as { date: "YYYY-MM-DD" }. */
function formatMatterOpenDate(openDate) {
  if (openDate == null || openDate === '') return '—';
  if (typeof openDate === 'string') return openDate;
  if (typeof openDate === 'object' && openDate.date) return openDate.date;
  return String(openDate);
}

// ─── Main page ─────────────────────────────────────────────────────────────

export default function MattersPage() {
  // Search state
  const [query, setQuery] = useState('');
  const [responsibleAtty, setResponsibleAtty] = useState('');
  const [originatingAtty, setOriginatingAtty] = useState('');
  const [responsibleStaff, setResponsibleStaff] = useState('');
  const [openDateFrom, setOpenDateFrom] = useState('');
  const [openDateTo, setOpenDateTo] = useState('');
  const [cfOC, setCfOC] = useState('');
  const [cfManufacturer, setCfManufacturer] = useState('');
  const [cfTrialDate, setCfTrialDate] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Results state
  const [matters, setMatters] = useState([]);
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
    if (responsibleAtty.trim()) params.set('responsible_attorney', responsibleAtty.trim());
    if (originatingAtty.trim()) params.set('originating_attorney', originatingAtty.trim());
    if (responsibleStaff.trim()) params.set('responsible_staff', responsibleStaff.trim());
    if (openDateFrom) params.set('open_date_from', openDateFrom);
    if (openDateTo) params.set('open_date_to', openDateTo);

    const cfFilters = [];
    if (cfOC.trim()) cfFilters.push({ name: 'O/C', value: cfOC.trim() });
    if (cfManufacturer.trim()) cfFilters.push({ name: 'Manufacturer', value: cfManufacturer.trim() });
    if (cfTrialDate.trim()) cfFilters.push({ name: 'Trial Date', value: cfTrialDate.trim() });
    if (cfFilters.length > 0) params.set('cf_filters', JSON.stringify(cfFilters));

    params.set('limit', '50');

    try {
      const res = await get(`/matters/search?${params.toString()}`);
      console.debug('[Matters] Search response', res);
      setMatters(res.data || []);
    } catch (err) {
      console.error('[Matters] Search error', err);
      setMatters([]);
    } finally {
      setLoading(false);
    }
  }

  function clearFilters() {
    setQuery('');
    setResponsibleAtty('');
    setOriginatingAtty('');
    setResponsibleStaff('');
    setOpenDateFrom('');
    setOpenDateTo('');
    setCfOC('');
    setCfManufacturer('');
    setCfTrialDate('');
    setMatters([]);
    setSearched(false);
    setExpandedId(null);
  }

  const hasFilters = query || responsibleAtty || originatingAtty || responsibleStaff || openDateFrom || openDateTo || cfOC || cfManufacturer || cfTrialDate;

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Matters</h1>

      {/* ── Search Panel ──────────────────────────────────────────────── */}
      <form onSubmit={handleSearch} className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 mb-6">

        {/* Row 1: Primary search */}
        <div className="flex gap-3 items-end">
          <div className="flex-[2] min-w-0">
            <FieldLabel htmlFor="m-query">Matter ID / Display Number</FieldLabel>
            <SearchInput id="m-query" placeholder="e.g. 00015-Agueros or 1830300500" value={query} onChange={setQuery} icon={Search} />
          </div>
          <div className="flex-1 min-w-0">
            <FieldLabel htmlFor="m-date-from">Open Date From</FieldLabel>
            <DateInput id="m-date-from" value={openDateFrom} onChange={setOpenDateFrom} />
          </div>
          <div className="flex-1 min-w-0">
            <FieldLabel htmlFor="m-ra">Responsible Attorney</FieldLabel>
            <SearchInput id="m-ra" placeholder="Attorney name" value={responsibleAtty} onChange={setResponsibleAtty} icon={User} />
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

        {/* Advanced Search toggle */}
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="flex items-center gap-1.5 text-xs text-blue-600 font-medium mt-3 hover:text-blue-700"
        >
          {showAdvanced ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          Advanced Search
        </button>

        {/* Row 2: Advanced filters */}
        {showAdvanced && (
          <div className="mt-3 pt-3 border-t border-slate-100">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <div>
                <FieldLabel htmlFor="m-oa">Originating Attorney</FieldLabel>
                <SearchInput id="m-oa" placeholder="Attorney name" value={originatingAtty} onChange={setOriginatingAtty} />
              </div>
              <div>
                <FieldLabel htmlFor="m-rs">Responsible Staff</FieldLabel>
                <SearchInput id="m-rs" placeholder="Staff name" value={responsibleStaff} onChange={setResponsibleStaff} />
              </div>
              <div>
                <FieldLabel htmlFor="m-oc">Opposing Counsel</FieldLabel>
                <SearchInput id="m-oc" placeholder="Opposing Counsel value" value={cfOC} onChange={setCfOC} />
              </div>
              <div>
                <FieldLabel htmlFor="m-mfg">Manufacturer</FieldLabel>
                <SearchInput id="m-mfg" placeholder="Manufacturer" value={cfManufacturer} onChange={setCfManufacturer} />
              </div>
              <div>
                <FieldLabel htmlFor="m-trial">Trial Date</FieldLabel>
                <SearchInput id="m-trial" placeholder="Trial date" value={cfTrialDate} onChange={setCfTrialDate} />
              </div>
            </div>
          </div>
        )}

        {/* Clear filters */}
        {hasFilters && (
          <button type="button" onClick={clearFilters} className="text-xs text-slate-400 hover:text-red-500 mt-3">
            Clear filters
          </button>
        )}
      </form>

      {/* ── Results Table ─────────────────────────────────────────────── */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-800">
            {searched ? `${matters.length} Result${matters.length !== 1 ? 's' : ''}` : 'Matters'}
          </h2>
          {!searched && (
            <span className="text-xs text-slate-400">Use the search above to find matters</span>
          )}
        </div>

        {loading ? (
          <div className="px-5 py-8 text-center">
            <Loader2 size={24} className="animate-spin text-blue-500 mx-auto mb-2" />
            <p className="text-sm text-slate-400">Searching Clio...</p>
          </div>
        ) : !searched ? (
          <div className="px-5 py-8 text-center">
            <Scale size={32} className="mx-auto text-slate-200 mb-3" />
            <p className="text-sm text-slate-400">Enter a search query above to find matters.</p>
          </div>
        ) : matters.length === 0 ? (
          <div className="px-5 py-8 text-center">
            <p className="text-sm text-slate-400">No matters matched your search criteria.</p>
          </div>
        ) : (
          <div>
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="text-left px-5 py-3 font-medium text-slate-600 w-8"></th>
                  <th className="text-left px-5 py-3 font-medium text-slate-600">Display Number</th>
                  <th className="text-left px-5 py-3 font-medium text-slate-600">Description</th>
                  <th className="text-left px-5 py-3 font-medium text-slate-600">Status</th>
                  <th className="text-left px-5 py-3 font-medium text-slate-600">Open Date</th>
                  <th className="text-left px-5 py-3 font-medium text-slate-600">Resp. Attorney</th>
                  <th className="text-left px-5 py-3 font-medium text-slate-600">Practice Area</th>
                </tr>
              </thead>
              <tbody>
                {matters.map(m => {
                  const isExpanded = expandedId === m.id;
                  const statusLabel = typeof m.status === 'string' ? m.status : (m.status?.name ?? m.status?.label ?? '—');
                  return (
                    <Fragment key={m.id}>
                      <tr
                        className="border-b border-slate-100 group cursor-pointer hover:bg-blue-50/80 transition"
                        onClick={() => setExpandedId(isExpanded ? null : m.id)}
                      >
                        <td className="px-5 py-3 w-8 align-middle">
                          {isExpanded ? <ChevronUp size={16} className="text-blue-500" /> : <ChevronDown size={16} className="text-slate-400 group-hover:text-blue-500" />}
                        </td>
                        <td className="px-5 py-3 font-medium text-blue-700 whitespace-nowrap align-middle">{m.display_number ?? '—'}</td>
                        <td className="px-5 py-3 text-slate-600 max-w-md align-middle">
                          <span className="block truncate" title={m.description || ''}>{m.description || '—'}</span>
                        </td>
                        <td className="px-5 py-3 align-middle">
                          {typeof statusLabel === 'string' && statusLabel !== '—' ? <StatusBadge status={statusLabel} /> : <span className="text-slate-400">—</span>}
                        </td>
                        <td className="px-5 py-3 text-slate-600 whitespace-nowrap align-middle">{formatMatterOpenDate(m.open_date)}</td>
                        <td className="px-5 py-3 text-slate-600 whitespace-nowrap align-middle">{m.responsible_attorney?.name || '—'}</td>
                        <td className="px-5 py-3 text-slate-600 whitespace-nowrap align-middle">{m.practice_area?.name || '—'}</td>
                      </tr>
                      {isExpanded && (
                        <tr className="bg-slate-50/60 border-b border-slate-100">
                          <td colSpan={7} className="px-5 pb-4 pt-2">
                            <MatterDetail matter={m} onClose={() => setExpandedId(null)} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
