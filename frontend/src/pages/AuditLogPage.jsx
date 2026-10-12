/**
 * Audit Log — consolidated batch view.
 *
 * Every execute() (single update, CSV bulk run, or revert) is stamped with a
 * batch_id, and this page shows ONE row per batch instead of the old
 * ever-growing per-change list. Concurrent executes by different users never
 * mix — their raw rows interleave by timestamp in the table, but each keeps
 * its own batch_id, so this view keeps them cleanly separated.
 *
 * Per-batch and full-log CSV downloads are generated on demand straight from
 * the database (nothing stored on disk, nothing to expire).
 */

import { useState, useEffect } from 'react';
import { get, downloadFile } from '../api/client';
import { Download, Loader2, Undo2 } from 'lucide-react';

const PAGE_SIZE = 100;

function StatusPill({ status, reverted }) {
  const styles = {
    success: 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-200',
    partial: 'bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-200',
    failed: 'bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-200',
  };
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`text-xs px-2 py-0.5 rounded-full ${styles[status] || 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300'}`}>
        {status}
      </span>
      {reverted && (
        <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300">
          <Undo2 size={11} /> reverted
        </span>
      )}
    </span>
  );
}

export default function AuditLogPage() {
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [downloadingId, setDownloadingId] = useState(null);
  const [error, setError] = useState(null);

  async function loadBatches(offset = 0) {
    const r = await get(`/audit/batches?limit=${PAGE_SIZE}&offset=${offset}`);
    const rows = r.data || [];
    setHasMore(rows.length === PAGE_SIZE);
    return rows;
  }

  useEffect(() => {
    loadBatches(0)
      .then(setBatches)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  async function handleLoadMore() {
    setLoadingMore(true);
    try {
      const more = await loadBatches(batches.length);
      setBatches(prev => [...prev, ...more]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleDownloadBatch(batchId) {
    setDownloadingId(batchId);
    setError(null);
    try {
      await downloadFile(`/audit/batch/${batchId}/download`, `audit_batch_${batchId}.csv`);
    } catch (err) {
      setError(err.message);
    } finally {
      setDownloadingId(null);
    }
  }

  async function handleDownloadFull() {
    setDownloadingId('__full__');
    setError(null);
    try {
      await downloadFile('/audit/download', 'audit_log_full.csv');
    } catch (err) {
      setError(err.message);
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">Audit Log</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            One record per operation batch — download a batch's CSV for the full row-by-row detail (successes and failures).
          </p>
        </div>
        <button
          onClick={handleDownloadFull}
          disabled={downloadingId === '__full__'}
          className="inline-flex items-center gap-2 px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 transition disabled:opacity-50"
        >
          {downloadingId === '__full__'
            ? <Loader2 size={14} className="animate-spin" />
            : <Download size={14} />}
          Download full log
        </button>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg p-4 text-sm text-red-700 dark:text-red-200 mb-4">{error}</div>
      )}

      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-700/50 border-b border-slate-200 dark:border-slate-700">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-300 whitespace-nowrap">Timestamp</th>
                <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-300">User</th>
                <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-300">Action</th>
                <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-300">Batch ID</th>
                <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-300 whitespace-nowrap">Rows</th>
                <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-300">Status</th>
                <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-300">Detail</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={7} className="px-4 py-4 text-slate-400">Loading...</td></tr>
              ) : batches.length === 0 ? (
                <tr><td colSpan={7} className="px-4 py-4 text-slate-400">No audit entries yet.</td></tr>
              ) : batches.map((b, i) => (
                <tr key={b.batch_id || `legacy-${i}`} className="border-b border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700">
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400 text-xs whitespace-nowrap">
                    {b.timestamp ? new Date(b.timestamp).toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-3 font-medium text-slate-800 dark:text-slate-100">{b.username}</td>
                  <td className="px-4 py-3">
                    <span className="text-xs bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-200 px-2 py-0.5 rounded-full">
                      {b.action}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="font-mono text-xs text-slate-500 dark:text-slate-400" title={b.batch_id || ''}>
                      {b.batch_id ? `${b.batch_id.slice(0, 8)}…` : '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-slate-600 dark:text-slate-300 text-xs whitespace-nowrap">
                    {b.total_rows}
                    {b.error_rows > 0 && (
                      <span className="text-red-600 dark:text-red-300"> ({b.error_rows} failed)</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <StatusPill status={b.status} reverted={b.reverted} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    {b.batch_id ? (
                      <button
                        onClick={() => handleDownloadBatch(b.batch_id)}
                        disabled={downloadingId === b.batch_id}
                        className="inline-flex items-center gap-1.5 px-2.5 py-1.5 border border-slate-300 dark:border-slate-600 rounded-lg text-xs font-medium text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition disabled:opacity-50"
                        title="Download this batch's full row-by-row CSV"
                      >
                        {downloadingId === b.batch_id
                          ? <Loader2 size={12} className="animate-spin" />
                          : <Download size={12} />}
                        CSV
                      </button>
                    ) : (
                      <span className="text-xs text-slate-300">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {hasMore && !loading && (
          <div className="px-4 py-3 border-t border-slate-100 dark:border-slate-700 text-center">
            <button
              onClick={handleLoadMore}
              disabled={loadingMore}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-600 dark:text-slate-300 hover:text-slate-800 transition disabled:opacity-50"
            >
              {loadingMore && <Loader2 size={14} className="animate-spin" />}
              Load more
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
