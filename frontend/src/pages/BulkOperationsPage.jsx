import { Upload } from 'lucide-react';

export default function BulkOperationsPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold text-slate-800 mb-6">Bulk Operations</h1>
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-8 text-center">
        <Upload size={48} className="mx-auto text-slate-300 mb-4" />
        <h2 className="text-lg font-semibold text-slate-700 mb-2">Coming Soon</h2>
        <p className="text-slate-500 text-sm">
          CSV upload, preview, and bulk update functionality will be built here.
        </p>
      </div>
    </div>
  );
}
