/**
 * Bulk Operations — three-tab page for updating Clio data.
 *
 * Tab 1: Update Single Custom Field   (JSON body)
 * Tab 2: Bulk Update Custom Fields     (CSV upload)
 * Tab 3: Bulk Update Matter Properties (CSV upload)
 *
 * Each tab follows a preview-then-execute workflow:
 *   Preview → review changes → Execute
 */

import { useState, useRef } from 'react';
import { post, postForm } from '../api/client';
import {
  Upload,
  FileSpreadsheet,
  Play,
  Eye,
  CheckCircle2,
  AlertCircle,
  ArrowRight,
  Loader2,
  X,
} from 'lucide-react';

const TABS = [
  { key: 'single',       label: 'Update Single Field' },
  { key: 'bulk-fields',  label: 'Bulk Update Fields (CSV)' },
  { key: 'bulk-matters', label: 'Bulk Update Matters (CSV)' },
];

// ─── Shared tiny components ────────────────────────────────────────────────

function StatusBanner({ status, message, onDismiss }) {
  if (!status) return null;
  const isError = status === 'error';
  return (
    <div className={`flex items-start gap-3 p-4 rounded-xl text-sm mb-5 ${
      isError ? 'bg-red-50 text-red-800 border border-red-200'
              : 'bg-green-50 text-green-800 border border-green-200'
    }`}>
      {isError ? <AlertCircle size={18} className="shrink-0 mt-0.5" />
               : <CheckCircle2 size={18} className="shrink-0 mt-0.5" />}
      <span className="flex-1">{message}</span>
      <button onClick={onDismiss} className="shrink-0 opacity-60 hover:opacity-100">
        <X size={16} />
      </button>
    </div>
  );
}

function ActionButton({ onClick, loading, disabled, variant = 'primary', icon: Icon, children }) {
  const base = 'inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed';
  const styles = variant === 'primary'
    ? `${base} bg-blue-600 text-white hover:bg-blue-700`
    : `${base} bg-emerald-600 text-white hover:bg-emerald-700`;
  return (
    <button onClick={onClick} disabled={disabled || loading} className={styles}>
      {loading ? <Loader2 size={16} className="animate-spin" /> : <Icon size={16} />}
      {children}
    </button>
  );
}

function Label({ children, htmlFor }) {
  return <label htmlFor={htmlFor} className="block text-sm font-medium text-slate-700 mb-1">{children}</label>;
}

function Input({ id, type = 'text', ...rest }) {
  return (
    <input
      id={id}
      type={type}
      className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
      {...rest}
    />
  );
}

// ─── Tab 1: Single field update ────────────────────────────────────────────

function SingleFieldTab() {
  const [matterId, setMatterId] = useState('');
  const [fieldName, setFieldName] = useState('');
  const [value, setValue] = useState('');
  const [preview, setPreview] = useState(null);
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState('');
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [loadingExecute, setLoadingExecute] = useState(false);

  const payload = { matter_id: matterId, field_name: fieldName, value };

  async function handlePreview() {
    console.debug('[BulkOps] Preview single field', payload);
    setStatus(null);
    setPreview(null);
    setLoadingPreview(true);
    try {
      const res = await post('/preview/update-field', payload);
      console.debug('[BulkOps] Preview response', res);
      setPreview(res);
    } catch (err) {
      console.error('[BulkOps] Preview error', err);
      setStatus('error');
      setMessage(err.message);
    } finally {
      setLoadingPreview(false);
    }
  }

  async function handleExecute() {
    console.debug('[BulkOps] Execute single field', payload);
    setLoadingExecute(true);
    try {
      const res = await post('/execute/update-field', payload);
      console.debug('[BulkOps] Execute response', res);
      setStatus('success');
      setMessage(res.message || 'Field updated successfully.');
      setPreview(null);
    } catch (err) {
      console.error('[BulkOps] Execute error', err);
      setStatus('error');
      setMessage(err.message);
    } finally {
      setLoadingExecute(false);
    }
  }

  const canPreview = matterId.trim() && fieldName.trim() && value.trim();

  return (
    <div className="space-y-5">
      <StatusBanner status={status} message={message} onDismiss={() => setStatus(null)} />

      {/* Input form */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <h3 className="text-base font-semibold text-slate-800 mb-4">Update a Single Custom Field</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <Label htmlFor="sf-matter">Matter ID</Label>
            <Input id="sf-matter" placeholder="e.g. 12345678" value={matterId} onChange={e => setMatterId(e.target.value)} />
          </div>
          <div>
            <Label htmlFor="sf-field">Custom Field Name</Label>
            <Input id="sf-field" placeholder="e.g. Case Type" value={fieldName} onChange={e => setFieldName(e.target.value)} />
          </div>
          <div>
            <Label htmlFor="sf-value">New Value</Label>
            <Input id="sf-value" placeholder="e.g. Litigation" value={value} onChange={e => setValue(e.target.value)} />
          </div>
        </div>
        <div className="flex gap-3 mt-5">
          <ActionButton onClick={handlePreview} loading={loadingPreview} disabled={!canPreview} icon={Eye}>
            Preview
          </ActionButton>
        </div>
      </div>

      {/* Preview card */}
      {preview && (
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
          <h3 className="text-base font-semibold text-slate-800 mb-4">Preview</h3>
          <div className="flex items-center gap-4 text-sm">
            <div className="flex-1 bg-slate-50 rounded-lg p-4">
              <p className="text-xs text-slate-500 mb-1">Current Value</p>
              <p className="font-medium text-slate-700">{preview.current_value ?? <span className="italic text-slate-400">empty</span>}</p>
            </div>
            <ArrowRight size={20} className="text-blue-500 shrink-0" />
            <div className="flex-1 bg-blue-50 rounded-lg p-4">
              <p className="text-xs text-blue-500 mb-1">New Value</p>
              <p className="font-medium text-blue-700">{preview.new_value ?? value}</p>
            </div>
          </div>
          {preview.matter_display_number && (
            <p className="text-xs text-slate-500 mt-3">
              Matter: {preview.matter_display_number} (ID {matterId})
              {preview.field_id && ` · Field ID: ${preview.field_id}`}
            </p>
          )}
          <div className="flex gap-3 mt-5">
            <ActionButton onClick={handleExecute} loading={loadingExecute} variant="execute" icon={Play}>
              Execute Update
            </ActionButton>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Tab 2 & 3: CSV-based bulk uploads ────────────────────────────────────

function CsvBulkTab({ previewEndpoint, executeEndpoint, title, description, extraFields }) {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [fieldName, setFieldName] = useState('');
  const [preview, setPreview] = useState(null);
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState('');
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [loadingExecute, setLoadingExecute] = useState(false);

  function buildFormData() {
    const fd = new FormData();
    fd.append('file', file);
    if (extraFields && fieldName.trim()) {
      fd.append('field_name', fieldName.trim());
    }
    return fd;
  }

  async function handlePreview() {
    console.debug(`[BulkOps] Preview CSV → ${previewEndpoint}`, file?.name);
    setStatus(null);
    setPreview(null);
    setLoadingPreview(true);
    try {
      const res = await postForm(previewEndpoint, buildFormData());
      console.debug('[BulkOps] CSV preview response', res);
      setPreview(res);
    } catch (err) {
      console.error('[BulkOps] CSV preview error', err);
      setStatus('error');
      setMessage(err.message);
    } finally {
      setLoadingPreview(false);
    }
  }

  async function handleExecute() {
    console.debug(`[BulkOps] Execute CSV → ${executeEndpoint}`, file?.name);
    setLoadingExecute(true);
    try {
      const res = await postForm(executeEndpoint, buildFormData());
      console.debug('[BulkOps] CSV execute response', res);
      setStatus('success');
      setMessage(res.message || `Bulk update complete — ${res.updated ?? '?'} rows processed.`);
      setPreview(null);
    } catch (err) {
      console.error('[BulkOps] CSV execute error', err);
      setStatus('error');
      setMessage(err.message);
    } finally {
      setLoadingExecute(false);
    }
  }

  function handleFileChange(e) {
    const selected = e.target.files?.[0] || null;
    console.debug('[BulkOps] File selected', selected?.name);
    setFile(selected);
    setPreview(null);
    setStatus(null);
  }

  function clearFile() {
    setFile(null);
    setPreview(null);
    if (fileRef.current) fileRef.current.value = '';
  }

  const rows = preview?.rows || preview?.data || [];
  const columns = rows.length > 0 ? Object.keys(rows[0]) : [];

  return (
    <div className="space-y-5">
      <StatusBanner status={status} message={message} onDismiss={() => setStatus(null)} />

      {/* Upload form */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <h3 className="text-base font-semibold text-slate-800 mb-1">{title}</h3>
        <p className="text-sm text-slate-500 mb-4">{description}</p>

        {extraFields && (
          <div className="mb-4 max-w-sm">
            <Label htmlFor="csv-field-name">Custom Field Name (optional)</Label>
            <Input
              id="csv-field-name"
              placeholder="e.g. Case Type"
              value={fieldName}
              onChange={e => setFieldName(e.target.value)}
            />
          </div>
        )}

        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 px-4 py-2.5 border-2 border-dashed border-slate-300 rounded-lg cursor-pointer hover:border-blue-400 hover:bg-blue-50 transition text-sm text-slate-600">
            <FileSpreadsheet size={18} className="text-slate-400" />
            {file ? file.name : 'Choose CSV file'}
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={handleFileChange}
            />
          </label>
          {file && (
            <button onClick={clearFile} className="text-slate-400 hover:text-red-500 transition">
              <X size={18} />
            </button>
          )}
        </div>

        <div className="flex gap-3 mt-5">
          <ActionButton onClick={handlePreview} loading={loadingPreview} disabled={!file} icon={Eye}>
            Preview
          </ActionButton>
        </div>
      </div>

      {/* Preview table */}
      {rows.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
            <h3 className="text-base font-semibold text-slate-800">
              Preview — {rows.length} row{rows.length !== 1 ? 's' : ''}
            </h3>
            <ActionButton onClick={handleExecute} loading={loadingExecute} variant="execute" icon={Play}>
              Execute Bulk Update
            </ActionButton>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  {columns.map(col => (
                    <th key={col} className="text-left px-5 py-3 font-medium text-slate-600 whitespace-nowrap">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i} className="border-b border-slate-100 hover:bg-slate-50">
                    {columns.map(col => (
                      <td key={col} className="px-5 py-3 text-slate-700 whitespace-nowrap">
                        {renderCellValue(row[col])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {preview && rows.length === 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 text-center">
          <p className="text-sm text-slate-500">No rows returned from preview. Check your CSV format.</p>
        </div>
      )}
    </div>
  );
}

function renderCellValue(val) {
  if (val === null || val === undefined) return <span className="text-slate-400 italic">null</span>;
  if (typeof val === 'boolean') return val ? 'true' : 'false';
  if (typeof val === 'object') return JSON.stringify(val);
  return String(val);
}

// ─── Page root ─────────────────────────────────────────────────────────────

export default function BulkOperationsPage() {
  const [activeTab, setActiveTab] = useState('single');

  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Bulk Operations</h1>

      {/* Tab bar */}
      <div className="flex gap-1 bg-slate-200 p-1 rounded-xl mb-6">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`flex-1 text-sm font-medium py-2.5 rounded-lg transition ${
              activeTab === key
                ? 'bg-white text-slate-800 shadow-sm'
                : 'text-slate-600 hover:text-slate-800'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab panels */}
      {activeTab === 'single' && <SingleFieldTab />}

      {activeTab === 'bulk-fields' && (
        <CsvBulkTab
          previewEndpoint="/preview/bulk-update-fields"
          executeEndpoint="/execute/bulk-update-fields"
          title="Bulk Update Custom Fields"
          description="Upload a CSV with columns: matter_id, field_name, value. Each row updates one custom field on one matter."
          extraFields
        />
      )}

      {activeTab === 'bulk-matters' && (
        <CsvBulkTab
          previewEndpoint="/preview/bulk-update-matters"
          executeEndpoint="/execute/bulk-update-matters"
          title="Bulk Update Matter Properties"
          description="Upload a CSV with columns: matter_id plus any matter properties (e.g. description, status). Each row updates one matter."
        />
      )}
    </div>
  );
}
