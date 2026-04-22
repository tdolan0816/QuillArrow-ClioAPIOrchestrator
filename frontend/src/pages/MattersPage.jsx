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

/**
 * Fixed-label custom field filters shown in the Advanced Search panel.
 * - `label`      is what stakeholders see in the UI.
 * - `clioName`   is the exact Matter custom field name to send as cf_filters[].name.
 * Change or extend this list to add more always-visible filter shortcuts.
 */
const FIXED_CF_FILTERS = [
  { label: 'Opposing Counsel', clioName: 'OC Firm Name' },
  { label: 'Manufacturer',     clioName: 'Vehicle Make' },
  { label: 'Trial Date',       clioName: 'Trial Date' },
];

export default function MattersPage() {
  // Search state
  const [query, setQuery] = useState('');
  const [responsibleAtty, setResponsibleAtty] = useState('');
  const [originatingAtty, setOriginatingAtty] = useState('');
  const [responsibleStaff, setResponsibleStaff] = useState('');
  const [openDateFrom, setOpenDateFrom] = useState('');
  const [openDateTo, setOpenDateTo] = useState('');

  // Values for the fixed CF filters (parallel to FIXED_CF_FILTERS above).
  const [fixedCfValues, setFixedCfValues] = useState(() => FIXED_CF_FILTERS.map(() => ''));

  // One additional generic CF filter: pick any custom field from the dropdown.
  const [extraCf, setExtraCf] = useState({ name: '', value: '' });

  const [showAdvanced, setShowAdvanced] = useState(false);

  // Available Matter custom fields (for the filter dropdowns)
  const [cfFieldOptions, setCfFieldOptions] = useState([]);
  const [cfFieldsLoading, setCfFieldsLoading] = useState(false);
  const [cfFieldsError, setCfFieldsError] = useState(null);

  // Results state
  const [matters, setMatters] = useState([]);
  const [warnings, setWarnings] = useState([]);
  const [cfDiagnostics, setCfDiagnostics] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  // Load Matter custom-field names once so the advanced filters can use a real dropdown.
  useEffect(() => {
    let cancelled = false;
    setCfFieldsLoading(true);
    setCfFieldsError(null);
    get('/matters/custom-field-names')
      .then(res => {
        if (cancelled) return;
        setCfFieldOptions(Array.isArray(res?.data) ? res.data : []);
      })
      .catch(err => {
        if (!cancelled) setCfFieldsError(err.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setCfFieldsLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  /** Find an option in cfFieldOptions by name (case-insensitive) to read its field_type. */
  function findFieldByName(name) {
    if (!name) return null;
    const needle = name.trim().toLowerCase();
    return cfFieldOptions.find(f => (f.name || '').toLowerCase() === needle) || null;
  }

  function updateFixedCfValue(index, value) {
    setFixedCfValues(current => current.map((v, i) => (i === index ? value : v)));
  }

  async function handleSearch(e) {
    if (e) e.preventDefault();
    setLoading(true);
    setSearched(true);
    setExpandedId(null);
    setWarnings([]);

    const params = new URLSearchParams();
    if (query.trim()) params.set('q', query.trim());
    if (responsibleAtty.trim()) params.set('responsible_attorney', responsibleAtty.trim());
    if (originatingAtty.trim()) params.set('originating_attorney', originatingAtty.trim());
    if (responsibleStaff.trim()) params.set('responsible_staff', responsibleStaff.trim());
    if (openDateFrom) params.set('open_date_from', openDateFrom);
    if (openDateTo) params.set('open_date_to', openDateTo);

    // Assemble cf_filters from the three fixed rows plus the optional extra row.
    const activeCfFilters = [];
    FIXED_CF_FILTERS.forEach((cfg, i) => {
      const v = (fixedCfValues[i] || '').trim();
      if (v) activeCfFilters.push({ name: cfg.clioName, value: v });
    });
    const extraName = (extraCf.name || '').trim();
    const extraValue = (extraCf.value || '').trim();
    if (extraName && extraValue) {
      activeCfFilters.push({ name: extraName, value: extraValue });
    }
    if (activeCfFilters.length > 0) {
      params.set('cf_filters', JSON.stringify(activeCfFilters));
      // Ask the API to include per-filter diagnostics so we can explain unmatched searches.
      params.set('debug', '1');
    }

    params.set('limit', '50');

    try {
      const res = await get(`/matters/search?${params.toString()}`);
      console.debug('[Matters] Search response', res);
      setMatters(res.data || []);
      setWarnings(Array.isArray(res?.warnings) ? res.warnings : []);
      setCfDiagnostics(Array.isArray(res?.cf_diagnostics) ? res.cf_diagnostics : []);
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
    setFixedCfValues(FIXED_CF_FILTERS.map(() => ''));
    setExtraCf({ name: '', value: '' });
    setMatters([]);
    setWarnings([]);
    setCfDiagnostics([]);
    setSearched(false);
    setExpandedId(null);
  }

  const hasCfFilterValues = fixedCfValues.some(v => (v || '').trim()) || (extraCf.value || '').trim();
  const hasFilters = query || responsibleAtty || originatingAtty || responsibleStaff || openDateFrom || openDateTo || hasCfFilterValues;

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
          <div className="mt-3 pt-3 border-t border-slate-100 space-y-4">
            {/* Attorney / staff filters */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <FieldLabel htmlFor="m-oa">Originating Attorney</FieldLabel>
                <SearchInput id="m-oa" placeholder="Attorney name" value={originatingAtty} onChange={setOriginatingAtty} />
              </div>
              <div>
                <FieldLabel htmlFor="m-rs">Responsible Staff</FieldLabel>
                <SearchInput id="m-rs" placeholder="Staff name" value={responsibleStaff} onChange={setResponsibleStaff} />
              </div>
            </div>

            {/* Three fixed-label custom field filters */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-medium text-slate-500">Quick custom field filters</span>
                {cfFieldsLoading && <span className="text-xs text-slate-400">Loading custom fields...</span>}
                {cfFieldsError && <span className="text-xs text-red-500">Could not load custom fields: {cfFieldsError}</span>}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                {FIXED_CF_FILTERS.map((cfg, i) => {
                  const field = findFieldByName(cfg.clioName);
                  const isDate = field?.field_type === 'date';
                  const inputId = `m-cf-fixed-${i}`;
                  return (
                    <div key={cfg.clioName}>
                      <FieldLabel htmlFor={inputId}>{cfg.label}</FieldLabel>
                      <input
                        id={inputId}
                        type={isDate ? 'date' : 'text'}
                        value={fixedCfValues[i]}
                        onChange={e => updateFixedCfValue(i, e.target.value)}
                        placeholder={isDate ? 'YYYY-MM-DD' : `Contains... (${cfg.clioName})`}
                        className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                      />
                    </div>
                  );
                })}
              </div>
            </div>

            {/* One "other" custom field filter using the full dropdown */}
            <div>
              <FieldLabel htmlFor="m-cf-extra-name">Other custom field</FieldLabel>
              <div className="grid grid-cols-1 md:grid-cols-12 gap-2">
                <div className="md:col-span-5">
                  <select
                    id="m-cf-extra-name"
                    value={extraCf.name}
                    onChange={e => setExtraCf(prev => ({ ...prev, name: e.target.value }))}
                    className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="">-- Pick a custom field --</option>
                    {cfFieldOptions.map(f => (
                      <option key={f.id} value={f.name}>{f.name}</option>
                    ))}
                  </select>
                </div>
                <div className="md:col-span-7">
                  {(() => {
                    const field = findFieldByName(extraCf.name);
                    const isDate = field?.field_type === 'date';
                    return (
                      <input
                        type={isDate ? 'date' : 'text'}
                        value={extraCf.value}
                        onChange={e => setExtraCf(prev => ({ ...prev, value: e.target.value }))}
                        placeholder={isDate ? 'YYYY-MM-DD' : 'Contains value...'}
                        disabled={!extraCf.name}
                        className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-slate-50 disabled:text-slate-400"
                      />
                    );
                  })()}
                </div>
              </div>
              <p className="text-[11px] text-slate-400 mt-2">
                Filters are combined with AND. Leave a value blank to skip that filter.
              </p>
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

      {/* ── Warnings (custom-field filter issues etc.) ─────────────────── */}
      {searched && warnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-4 text-sm text-amber-800">
          <p className="font-semibold mb-1">Some filters were not applied</p>
          <ul className="list-disc list-inside space-y-0.5">
            {warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        </div>
      )}

      {/* ── Custom field filter diagnostics (only shown when CF filters were used) ─── */}
      {searched && cfDiagnostics.length > 0 && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl px-4 py-3 mb-4 text-xs text-slate-700">
          <p className="font-semibold text-slate-800 mb-2">Custom field filter diagnostics</p>
          <ul className="space-y-2">
            {cfDiagnostics.map((d, i) => (
              <li key={i} className="font-mono">
                <div>
                  field_id={d.field_id} type={d.field_type || 'text'} value_sent="{d.value_sent}"
                </div>
                <div>
                  matters_with_value={d.matters_with_a_value} matters_matched={d.matters_matched}
                </div>
                {Array.isArray(d.picklist_option_ids) && d.picklist_option_ids.length > 0 && (
                  <div className="text-slate-500">
                    resolved picklist option ids: [{d.picklist_option_ids.join(', ')}]
                  </div>
                )}
                {Array.isArray(d.sample_stored_values) && d.sample_stored_values.length > 0 && (
                  <div className="text-slate-500">
                    examples: {d.sample_stored_values.slice(0, 3).map(s => (
                      `#${s.display_number ?? s.matter_id} → [${(s.stored_forms || []).join(' | ')}]`
                    )).join('  ·  ')}
                  </div>
                )}
              </li>
            ))}
          </ul>
          <p className="text-slate-500 mt-2 font-sans">
            If matters_with_value is 0, the pool of matters scanned doesn’t have this field set anywhere — it may live on Contacts, or the matter you’re testing isn’t in the first 500 results. If matters_with_value is greater than 0 but matters_matched is 0, examine the "stored" values above — that’s what we’re comparing your input against.
          </p>
        </div>
      )}

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
