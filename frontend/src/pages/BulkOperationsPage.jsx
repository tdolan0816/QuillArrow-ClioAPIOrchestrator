/**
 * Bulk Operations — three-tab page for updating Clio data.
 *
 * Tab 1: Update Single Custom Field   (JSON body)
 * Tab 2: Bulk Update Custom Fields     (CSV upload)
 * Tab 3: Bulk Update Matter Properties (CSV upload)
 *
 * Each tab follows a preview-then-execute workflow:
 *   Preview → review changes → Execute
 *
 * After a successful Execute, the server returns a `batch_id` that groups every
 * audit row written for that call. The UI holds onto that id and exposes a
 * "Revert last execution" button, which POSTs /api/execute/revert/{batch_id}.
 * The revert itself is logged to the audit trail, so it's auditable and
 * re-revertible.
 */

import { useState, useRef } from 'react';
import { post, postForm, downloadFile } from '../api/client';
import {
  FileSpreadsheet,
  Play,
  Eye,
  CheckCircle2,
  AlertCircle,
  ArrowRight,
  Loader2,
  X,
  Download,
  Undo2,
  Info,
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

/**
 * Amber "Revert last execution" banner shown after any successful execute that
 * returned a batch_id. Includes an inline info tooltip explaining what revert
 * does so stakeholders don't have to read docs.
 */
function RevertPanel({ lastBatch, onRevert, loadingRevert }) {
  if (!lastBatch?.batchId) return null;
  const { batchId, summary, completed = 0 } = lastBatch;
  return (
    <div className="flex items-start justify-between gap-4 p-4 rounded-xl border border-amber-200 bg-amber-50 mb-5">
      <div className="flex items-start gap-3 text-sm text-amber-900">
        <Info size={18} className="shrink-0 mt-0.5 text-amber-600" />
        <div>
          <p className="font-medium">
            {summary || `Execution complete.`}
            {completed ? ` ${completed} row${completed === 1 ? '' : 's'} are available to revert.` : ''}
          </p>
          <p className="text-xs text-amber-700 mt-1">
            Revert restores the exact prior values for every row that this execution succeeded on.
            The revert itself is written to the audit log and can itself be reverted.
            Once reverted, this batch cannot be reverted again.
          </p>
          <p className="text-[11px] text-amber-600 mt-1 font-mono">batch id: {batchId}</p>
        </div>
      </div>
      <button
        type="button"
        onClick={onRevert}
        disabled={loadingRevert}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-amber-900 bg-amber-100 hover:bg-amber-200 border border-amber-300 transition disabled:opacity-50 shrink-0"
        title="Undo every row that succeeded in the last execution by restoring prior values."
      >
        {loadingRevert ? <Loader2 size={16} className="animate-spin" /> : <Undo2 size={16} />}
        Revert last execution
      </button>
    </div>
  );
}

// ─── Tab 1: Single field update ────────────────────────────────────────────

function SingleFieldTab() {
  const [displayNumber, setDisplayNumber] = useState('');
  const [matterId, setMatterId] = useState('');
  const [fieldName, setFieldName] = useState('');
  const [value, setValue] = useState('');
  const [preview, setPreview] = useState(null);
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState('');
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [loadingExecute, setLoadingExecute] = useState(false);
  const [lastBatch, setLastBatch] = useState(null);
  const [loadingRevert, setLoadingRevert] = useState(false);

  function buildPayload() {
    return {
      display_number: displayNumber.trim(),
      matter_id: matterId.trim(),
      field_name: fieldName,
      value,
    };
  }

  async function handlePreview() {
    const payload = buildPayload();
    setStatus(null);
    setPreview(null);
    setLoadingPreview(true);
    try {
      const res = await post('/preview/update-field', payload);
      setPreview(res);
    } catch (err) {
      setStatus('error');
      setMessage(err.message);
    } finally {
      setLoadingPreview(false);
    }
  }

  async function handleExecute() {
    const payload = buildPayload();
    setLoadingExecute(true);
    try {
      const res = await post('/execute/update-field', payload);
      if (res?.success) {
        setStatus('success');
        setMessage('Field updated successfully.');
        setPreview(null);
        setLastBatch({
          batchId: res.batch_id,
          completed: 1,
          summary: 'Single custom field updated.',
        });
      } else {
        setStatus('error');
        setMessage(res?.error || 'Update failed.');
      }
    } catch (err) {
      setStatus('error');
      setMessage(err.message);
    } finally {
      setLoadingExecute(false);
    }
  }

  async function handleRevert() {
    if (!lastBatch?.batchId) return;
    setLoadingRevert(true);
    try {
      const res = await post(`/execute/revert/${lastBatch.batchId}`, {});
      if (res?.success) {
        setStatus('success');
        setMessage(`Reverted ${res.reverted} row${res.reverted === 1 ? '' : 's'}.`);
      } else {
        setStatus('error');
        setMessage(`Revert completed with ${res?.failed ?? '?'} failure(s).`);
      }
      setLastBatch(null); // batch can't be reverted again
    } catch (err) {
      setStatus('error');
      setMessage(err.message);
    } finally {
      setLoadingRevert(false);
    }
  }

  const hasIdentifier = displayNumber.trim() || matterId.trim();
  const canPreview = hasIdentifier && fieldName.trim() && value.trim();

  return (
    <div className="space-y-5">
      <StatusBanner status={status} message={message} onDismiss={() => setStatus(null)} />
      <RevertPanel lastBatch={lastBatch} onRevert={handleRevert} loadingRevert={loadingRevert} />

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <h3 className="text-base font-semibold text-slate-800 mb-4">Update a Single Custom Field</h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <div>
            <Label htmlFor="sf-display">Matter Display Number</Label>
            <Input id="sf-display" placeholder="e.g. 00015-Agueros" value={displayNumber} onChange={e => setDisplayNumber(e.target.value)} />
          </div>
          <div className="relative">
            <Label htmlFor="sf-matter">Matter ID</Label>
            <Input id="sf-matter" placeholder="e.g. 1830300500" value={matterId} onChange={e => setMatterId(e.target.value)} />
          </div>
        </div>
        <p className="text-xs text-slate-400 mb-4">
          Use either Display Number or Matter ID. If both are provided, Matter ID takes priority.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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

      {preview && (
        <PreviewCard preview={preview} value={value} displayNumber={displayNumber} matterId={matterId}
          onExecute={handleExecute} loadingExecute={loadingExecute} />
      )}
    </div>
  );
}

function PreviewCard({ preview, value, displayNumber, onExecute, loadingExecute }) {
  const changes = preview.preview || [];
  const errors = preview.errors || [];
  const change = changes[0];

  if (errors.length > 0 && !change) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-red-200 p-6">
        <h3 className="text-base font-semibold text-red-700 mb-2">Preview Failed</h3>
        {errors.map((e, i) => <p key={i} className="text-sm text-red-600">{e}</p>)}
      </div>
    );
  }

  if (!change) return null;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <h3 className="text-base font-semibold text-slate-800 mb-4">Preview</h3>
      <div className="flex items-center gap-4 text-sm">
        <div className="flex-1 bg-slate-50 rounded-lg p-4">
          <p className="text-xs text-slate-500 mb-1">Current Value</p>
          <p className="font-medium text-slate-700">{change.current_value ?? <span className="italic text-slate-400">empty</span>}</p>
        </div>
        <ArrowRight size={20} className="text-blue-500 shrink-0" />
        <div className="flex-1 bg-blue-50 rounded-lg p-4">
          <p className="text-xs text-blue-500 mb-1">New Value</p>
          <p className="font-medium text-blue-700">{change.new_value ?? value}</p>
        </div>
      </div>
      <p className="text-xs text-slate-500 mt-3">
        Matter ID: {change.matter_id}
        {displayNumber.trim() && ` · Display #: ${displayNumber}`}
        {change.field_name && ` · Field: ${change.field_name}`}
        {change.field_type && ` (${change.field_type})`}
        {` · Action: ${change.action}`}
      </p>
      <div className="flex gap-3 mt-5">
        <ActionButton onClick={onExecute} loading={loadingExecute} variant="execute" icon={Play}>
          Execute Update
        </ActionButton>
      </div>
    </div>
  );
}

// ─── Tab 2 & 3: CSV-based bulk uploads ────────────────────────────────────

function CsvBulkTab({ previewEndpoint, executeEndpoint, title, description, extraFields, templateEndpoint, templateFilename }) {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [fieldName, setFieldName] = useState('');
  const [preview, setPreview] = useState(null);
  const [status, setStatus] = useState(null);
  const [message, setMessage] = useState('');
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [loadingExecute, setLoadingExecute] = useState(false);
  const [loadingTemplate, setLoadingTemplate] = useState(false);
  const [lastBatch, setLastBatch] = useState(null);
  const [loadingRevert, setLoadingRevert] = useState(false);

  async function handleDownloadTemplate() {
    if (!templateEndpoint) return;
    setLoadingTemplate(true);
    try {
      await downloadFile(templateEndpoint, templateFilename);
    } catch (err) {
      setStatus('error');
      setMessage(err.message || 'Template download failed.');
    } finally {
      setLoadingTemplate(false);
    }
  }

  function buildFormData() {
    const fd = new FormData();
    fd.append('file', file);
    if (extraFields && fieldName.trim()) {
      fd.append('field_name', fieldName.trim());
    }
    return fd;
  }

  async function handlePreview() {
    setStatus(null);
    setPreview(null);
    setLoadingPreview(true);
    try {
      const res = await postForm(previewEndpoint, buildFormData());
      setPreview(res);
    } catch (err) {
      setStatus('error');
      setMessage(err.message);
    } finally {
      setLoadingPreview(false);
    }
  }

  async function handleExecute() {
    setLoadingExecute(true);
    try {
      const res = await postForm(executeEndpoint, buildFormData());
      const completed = res?.completed ?? 0;
      const failed = res?.failed ?? 0;
      if (res?.success) {
        setStatus('success');
        setMessage(`Bulk update complete — ${completed} row${completed === 1 ? '' : 's'} succeeded.`);
      } else {
        setStatus('error');
        setMessage(
          `Bulk update finished with ${failed} error${failed === 1 ? '' : 's'}. ` +
          `${completed} row${completed === 1 ? '' : 's'} did succeed` +
          (completed > 0 ? ' and can still be reverted.' : '.')
        );
      }
      setPreview(null);
      if (res?.batch_id && completed > 0) {
        setLastBatch({
          batchId: res.batch_id,
          completed,
          summary: `Bulk execution finished with ${completed} successful row${completed === 1 ? '' : 's'}.`,
        });
      }
    } catch (err) {
      setStatus('error');
      setMessage(err.message);
    } finally {
      setLoadingExecute(false);
    }
  }

  async function handleRevert() {
    if (!lastBatch?.batchId) return;
    setLoadingRevert(true);
    try {
      const res = await post(`/execute/revert/${lastBatch.batchId}`, {});
      const reverted = res?.reverted ?? 0;
      const failed = res?.failed ?? 0;
      if (res?.success) {
        setStatus('success');
        setMessage(`Reverted ${reverted} row${reverted === 1 ? '' : 's'}.`);
      } else {
        setStatus('error');
        setMessage(
          `Revert finished with ${failed} error${failed === 1 ? '' : 's'}; ` +
          `${reverted} row${reverted === 1 ? '' : 's'} were restored.`
        );
      }
      setLastBatch(null);
    } catch (err) {
      setStatus('error');
      setMessage(err.message);
    } finally {
      setLoadingRevert(false);
    }
  }

  function handleFileChange(e) {
    const selected = e.target.files?.[0] || null;
    setFile(selected);
    setPreview(null);
    setStatus(null);
  }

  function clearFile() {
    setFile(null);
    setPreview(null);
    if (fileRef.current) fileRef.current.value = '';
  }

  const rows = preview?.preview || preview?.rows || preview?.data || [];
  const previewErrors = preview?.errors || [];
  const hiddenCols = new Set(['patch_body', 'resolved_value', 'previous_values']);
  const columns = rows.length > 0
    ? Object.keys(rows[0]).filter(c => !hiddenCols.has(c))
    : [];

  return (
    <div className="space-y-5">
      <StatusBanner status={status} message={message} onDismiss={() => setStatus(null)} />
      <RevertPanel lastBatch={lastBatch} onRevert={handleRevert} loadingRevert={loadingRevert} />

      {/* Upload form */}
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            <h3 className="text-base font-semibold text-slate-800 mb-1">{title}</h3>
            <p className="text-sm text-slate-500">{description}</p>
          </div>
          {templateEndpoint && (
            <button
              type="button"
              onClick={handleDownloadTemplate}
              disabled={loadingTemplate}
              className="inline-flex items-center gap-2 px-3 py-2 border border-slate-300 rounded-lg text-sm font-medium text-slate-700 hover:bg-slate-50 transition disabled:opacity-50 shrink-0"
              title="Download a CSV template with the correct column headers"
            >
              {loadingTemplate ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
              CSV template
            </button>
          )}
        </div>

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
        <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
          {previewErrors.length > 0 ? (
            <div>
              <h3 className="text-base font-semibold text-red-700 mb-3">Preview Errors</h3>
              <ul className="space-y-1">
                {previewErrors.map((e, i) => (
                  <li key={i} className="text-sm text-red-600">{e}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-slate-500 text-center">No rows returned from preview. Check your CSV format.</p>
          )}
        </div>
      )}

      {rows.length > 0 && previewErrors.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
          <h4 className="text-sm font-semibold text-amber-800 mb-2">
            {previewErrors.length} row{previewErrors.length !== 1 ? 's' : ''} had issues:
          </h4>
          <ul className="space-y-1">
            {previewErrors.map((e, i) => (
              <li key={i} className="text-xs text-amber-700">{e}</li>
            ))}
          </ul>
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
          templateEndpoint="/templates/bulk-update-fields.csv"
          templateFilename="bulk_update_fields_template.csv"
          title="Bulk Update Custom Fields"
          description="Upload a CSV with columns: matter_id (or display_number), field_name, value. You can use display_number instead of matter_id to identify matters. Each row updates one custom field on one matter."
          extraFields
        />
      )}

      {activeTab === 'bulk-matters' && (
        <CsvBulkTab
          previewEndpoint="/preview/bulk-update-matters"
          executeEndpoint="/execute/bulk-update-matters"
          templateEndpoint="/templates/bulk-update-matters.csv"
          templateFilename="bulk_update_matters_template.csv"
          title="Bulk Update Matter Properties"
          description="Upload a CSV with columns: matter_id (or display_number) plus any matter properties (e.g. description, status). You can use display_number instead of matter_id. Each row updates one matter."
        />
      )}
    </div>
  );
}
