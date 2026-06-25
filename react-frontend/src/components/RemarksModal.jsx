import React from 'react';

export default function RemarksModal({ tenders, filterTenderId, onClose }) {
  const allRemarks = [];
  tenders.forEach(t => {
    if (filterTenderId && t.id !== filterTenderId) return;
    if (t.remarks) {
      t.remarks.forEach(r => {
        if (r.fieldName !== 'Initial Setup') {
          allRemarks.push({ tenderNo: t.tenderNo || '—', ...r });
        }
      });
    }
  });

  const filterTenderNo = filterTenderId
    ? (tenders.find(t => t.id === filterTenderId)?.tenderNo || '—')
    : null;

  const title = filterTenderNo
    ? `Remarks — ${filterTenderNo}`
    : 'Audit & Remarks Log (All Tenders)';

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: '900px', width: '95vw' }}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button onClick={onClose} className="btn btn-ghost" style={{ padding: '4px 8px' }}>✕</button>
        </div>
        <div className="modal-body" style={{ padding: 0, overflowX: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                {!filterTenderId && <th>Tender No</th>}
                <th>Field</th>
                <th>Old Value</th>
                <th>New Value</th>
                <th>Remark</th>
                <th>User</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              {allRemarks.length === 0 ? (
                <tr>
                  <td colSpan={filterTenderId ? 6 : 7} style={{ textAlign: 'center', padding: '40px' }}>
                    <span style={{ color: 'var(--text-muted)' }}>No audit history available.</span>
                  </td>
                </tr>
              ) : (
                allRemarks.map((r, index) => (
                  <tr key={index}>
                    {!filterTenderId && <td style={{ fontWeight: 500 }}>{r.tenderNo}</td>}
                    <td>{r.fieldName}</td>
                    <td style={{ color: 'var(--danger)' }}>{r.oldVal}</td>
                    <td style={{ color: 'var(--success)' }}>{r.newVal}</td>
                    <td style={{ fontStyle: 'italic', color: 'var(--text-muted)' }}>{r.remark}</td>
                    <td>{r.changedBy}</td>
                    <td style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{r.changedAt}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="modal-footer">
          <button onClick={onClose} className="btn btn-secondary">Close</button>
        </div>
      </div>
    </div>
  );
}
