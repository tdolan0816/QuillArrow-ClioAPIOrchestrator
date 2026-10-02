/**
 * Template Mass Update — bulk find/replace across Clio document templates.
 *
 * Workflow mirrors Bulk Operations: upload a two-column lookup CSV (old,new),
 * pick a scope, PREVIEW (dry run, counts only), then EXECUTE (admin only —
 * rewrites matching templates and uploads them back to Clio as NEW templates;
 * originals are never touched in v1).
 *
 * Both actions start a background job and poll GET /api/execute/jobs/{id} so
 * Azure's ~230s gateway timeout never applies.
 */

import { useState, useRef } from 'react';
import { get, post, postForm, downloadFile } from '../api/client';
import { useAuth } from '../context/AuthContext';
import {
  FileSpreadsheet,
  Eye,
  Play,
  Download,
  Loader2,
  CheckCircle2,
  AlertCircle,
  X,
  FileText,
  Info,
} from 'lucide-react';

const POLL_MS = 2000;

function Banner({ status, message, onDismiss }) {
  if (!status) return null;
  const isError = status === 'error';
  return (
    <div
      className={`flex items-start gap-3 p-4 rounded-xl text-sm mb-5 ${
        isError
          ? 'bg-red-50 text-red-800 border border-red-200'
          : 'bg-green-50 text-green-800 border border-green-200'
      }`}
    >
      {isError ? (
        <AlertCircle size={18} className="shrink-0 mt-0.5" />
      ) : (
        <CheckCircle2 size={18} className="shrink-0 mt-0.5" />
      )}
      <span className="flex-1 whitespace-pre-wrap">{message}</span>
      {onDismiss && (
        <button onClick={onDismiss} className="shrink-0 opacity-60 hover:opacity-100">
          <X size={16} />
        </button>
      )}
    </div>
  );
}

function Checkbox({ label, checked, onChange, hint }) {
  return (
    <label className="flex items-start gap-2 text-sm text-slate-700 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
      />
      <span>
        {label}
        {hint && <span className="block text-xs text-slate-400">{hint}</span>}
      </span>
    </label>
  );
}

function ProgressBar({ job }) {
  if (!job) return null;
  const pct = job.percent || 0;
  return (
    <div className="mb-5">
      <div className="flex justify-between text-xs text-slate-500 mb-1">
        <span>{job.message || `${job.phase || 'working'}…`}</span>
        <span>
          {job.processed || 0}/{job.total || 0} ({pct}%)
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-slate-200 overflow-hidden">
        <div className="h-full bg-blue-600 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ResultsTable({ results, executed }) {
  if (!results || results.length === 0) return null;
  const withMatches = results.filter((r) => (r.matches || 0) > 0 || r.status === 'error');
  const totalMatches = results.reduce((a, r) => a + (r.matches || 0), 0);
  return (
    <div className="mt-6">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-slate-700">
          {executed ? 'Update results' : 'Preview — matches found'}{' '}
          <span className="text-slate-400 font-normal">
            ({results.length} template(s), {totalMatches} total match(es))
          </span>
        </h3>
      </div>
      <div className="overflow-auto border border-slate-200 rounded-lg max-h-96">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 text-xs uppercase sticky top-0">
            <tr>
              <th className="text-left px-3 py-2">Template</th>
              <th className="text-right px-3 py-2">Matches</th>
              <th className="text-left px-3 py-2">Status</th>
              {executed && <th className="text-left px-3 py-2">New template</th>}
              {executed && <th className="text-left px-3 py-2">Verified</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {(withMatches.length ? withMatches : results).map((r, i) => (
              <tr key={`${r.template_id}-${i}`} className="hover:bg-slate-50">
                <td className="px-3 py-2">
                  <div className="font-medium text-slate-700">{r.filename}</div>
                  <div className="text-xs text-slate-400 font-mono">{r.template_id}</div>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{r.matches ?? '—'}</td>
                <td className="px-3 py-2">
                  {r.status === 'error' ? (
                    <span className="text-red-600" title={r.error}>
                      error
                    </span>
                  ) : (
                    <span className="text-emerald-600">ok</span>
                  )}
                </td>
                {executed && (
                  <td className="px-3 py-2 font-mono text-xs">{r.new_template_id || '—'}</td>
                )}
                {executed && (
                  <td className="px-3 py-2">
                    {r.new_template_id ? (
                      r.verified_clean ? (
                        <span className="text-emerald-600">clean</span>
                      ) : (
                        <span className="text-amber-600">
                          {r.old_remaining} left
                        </span>
                      )
                    ) : (
                      '—'
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function resultsToCsv(results, executed) {
  const headers = executed
    ? ['template_id', 'filename', 'matches', 'status', 'new_template_id', 'new_filename', 'verified_clean', 'old_remaining', 'error']
    : ['template_id', 'filename', 'matches', 'status', 'error'];
  const esc = (v) => {
    const s = v === undefined || v === null ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [headers.join(',')];
  for (const r of results) {
    lines.push(headers.map((h) => esc(r[h])).join(','));
  }
  return lines.join('\r\n');
}

export default function TemplateMassUpdatePage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [file, setFile] = useState(null);
  const [scope, setScope] = useState('all');
  const [templateIds, setTemplateIds] = useState('');
  const [ignoreCase, setIgnoreCase] = useState(false);
  const [headersFooters, setHeadersFooters] = useState(true);
  const [textboxes, setTextboxes] = useState(true);
  const [filenameSuffix, setFilenameSuffix] = useState('');
  const [confirmExecute, setConfirmExecute] = useState(false);

  const [banner, setBanner] = useState(null); // {status, message}
  const [job, setJob] = useState(null);
  const [results, setResults] = useState(null);
  const [executed, setExecuted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [activeJobId, setActiveJobId] = useState(null);
  const fileRef = useRef(null);

  function buildForm(includeSuffix) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('scope', scope);
    fd.append('template_ids', templateIds);
    fd.append('ignore_case', String(ignoreCase));
    fd.append('include_headers_footers', String(headersFooters));
    fd.append('include_textboxes', String(textboxes));
    if (includeSuffix) fd.append('filename_suffix', filenameSuffix);
    return fd;
  }

  async function pollJob(jobId) {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      let j;
      try {
        j = await get(`/execute/jobs/${jobId}`);
      } catch {
        continue; // transient (DB waking up) — keep polling
      }
      setJob(j);
      if (j.state && j.state !== 'running') return j;
    }
  }

  async function run(kind) {
    if (!file) {
      setBanner({ status: 'error', message: 'Choose a lookup CSV first.' });
      return;
    }
    if (kind === 'execute' && !confirmExecute) {
      setBanner({ status: 'error', message: 'Tick the confirmation box before executing.' });
      return;
    }
    setBusy(true);
    setBanner(null);
    setResults(null);
    setJob(null);
    setExecuted(kind === 'execute');
    try {
      const endpoint = kind === 'execute' ? '/template-update/execute' : '/template-update/preview';
      const start = await postForm(endpoint, buildForm(kind === 'execute'));
      setActiveJobId(start.job_id);
      const final = await pollJob(start.job_id);
      setResults(final.results || []);
      setBanner({
        status: final.state === 'ok' ? 'success' : 'error',
        message: final.message || `Job ${final.state}.`,
      });
    } catch (err) {
      setBanner({ status: 'error', message: err.message });
    } finally {
      setBusy(false);
      setActiveJobId(null);
    }
  }

  async function cancel() {
    if (!activeJobId) return;
    try {
      await post(`/execute/jobs/${activeJobId}/cancel`, {});
      setBanner({ status: 'error', message: 'Cancellation requested…' });
    } catch {
      /* 409 = already finished; harmless */
    }
  }

  function downloadReport() {
    if (!results || !results.length) return;
    const csv = resultsToCsv(results, executed);
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `template-update-${executed ? 'results' : 'preview'}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="max-w-5xl">
      <div className="flex items-center gap-3 mb-1">
        <FileText className="text-blue-600" size={24} />
        <h1 className="text-xl font-semibold text-slate-800">Template Mass Update</h1>
      </div>
      <p className="text-sm text-slate-500 mb-6">
        Find &amp; replace text across Clio document templates in bulk. Preview counts matches
        without changing anything; Execute uploads rewritten copies as <strong>new</strong>{' '}
        templates (originals are never modified or deleted).
      </p>

      <Banner status={banner?.status} message={banner?.message} onDismiss={() => setBanner(null)} />

      <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-6">
        {/* Lookup CSV */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-sm font-medium text-slate-700">Lookup CSV (old,new)</label>
            <button
              type="button"
              onClick={() => downloadFile('/template-update/lookup-template.csv', 'lookup-template.csv')}
              className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
            >
              <Download size={14} /> Sample CSV
            </button>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".csv"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="block w-full text-sm text-slate-600 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
          />
          {file && (
            <p className="mt-1 text-xs text-slate-400 flex items-center gap-1">
              <FileSpreadsheet size={12} /> {file.name}
            </p>
          )}
        </div>

        {/* Scope */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Scope</label>
          <div className="flex gap-6 text-sm">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" checked={scope === 'all'} onChange={() => setScope('all')} />
              All templates
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" checked={scope === 'ids'} onChange={() => setScope('ids')} />
              Specific template IDs
            </label>
          </div>
          {scope === 'ids' && (
            <textarea
              value={templateIds}
              onChange={(e) => setTemplateIds(e.target.value)}
              placeholder="Template IDs, comma or newline separated"
              rows={3}
              className="mt-2 w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          )}
        </div>

        {/* Options */}
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-2">Options</label>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Checkbox label="Headers & footers" checked={headersFooters} onChange={setHeadersFooters} />
            <Checkbox label="Text boxes / shapes" checked={textboxes} onChange={setTextboxes} />
            <Checkbox label="Case-insensitive" checked={ignoreCase} onChange={setIgnoreCase} />
          </div>
        </div>

        {/* Progress */}
        {busy && <ProgressBar job={job} />}

        {/* Preview action */}
        <div className="flex items-center gap-3 pt-2 border-t border-slate-100">
          <button
            onClick={() => run('preview')}
            disabled={busy}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy && !executed ? <Loader2 size={16} className="animate-spin" /> : <Eye size={16} />}
            Preview (dry run)
          </button>
          {busy && activeJobId && (
            <button
              onClick={cancel}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium text-slate-600 border border-slate-300 hover:bg-slate-50"
            >
              <X size={16} /> Cancel
            </button>
          )}
          {results && (
            <button
              onClick={downloadReport}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium text-slate-600 border border-slate-300 hover:bg-slate-50"
            >
              <Download size={16} /> Download report
            </button>
          )}
        </div>

        {/* Execute (admin only) */}
        {isAdmin ? (
          <div className="pt-4 border-t border-slate-100 space-y-3">
            <div className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3">
              <Info size={14} className="shrink-0 mt-0.5" />
              <span>
                Execute creates a NEW template per match (dated suffix). Nothing is overwritten or
                deleted. Verify the preview counts first.
              </span>
            </div>
            <div className="flex flex-wrap items-end gap-4">
              <div className="flex-1 min-w-48">
                <label className="block text-sm font-medium text-slate-700 mb-1">
                  New filename suffix
                </label>
                <input
                  type="text"
                  value={filenameSuffix}
                  onChange={(e) => setFilenameSuffix(e.target.value)}
                  placeholder="_Updated_MMDDYY (default)"
                  className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
            <Checkbox
              label="I reviewed the preview and want to create updated templates in Clio."
              checked={confirmExecute}
              onChange={setConfirmExecute}
            />
            <button
              onClick={() => run('execute')}
              disabled={busy || !confirmExecute}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {busy && executed ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
              Execute update
            </button>
          </div>
        ) : (
          <p className="pt-4 border-t border-slate-100 text-xs text-slate-400">
            Executing updates requires an admin account. You can still run previews.
          </p>
        )}

        <ResultsTable results={results} executed={executed} />
      </div>
    </div>
  );
}
