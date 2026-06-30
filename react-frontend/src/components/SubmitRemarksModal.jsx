import React, { useState } from 'react';

export default function SubmitRemarksModal({ tenderNo, changedFields, onCancel, onSave }) {
  const [remarks,      setRemarks]      = useState({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    for (let change of changedFields) {
      if (!remarks[change.field] || !remarks[change.field].trim()) {
        alert(`Please provide a remark for: ${change.field}`);
        return;
      }
    }
    setIsSubmitting(true);
    try {
      await onSave(remarks);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: '560px' }}>
        <div className="modal-header">
          <div>
            <h3 style={{ margin: 0 }}>Commit Changes</h3>
            {tenderNo && (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                Tender: {tenderNo}
              </div>
            )}
          </div>
          <button onClick={onCancel} className="btn btn-ghost" style={{ padding: '4px 8px' }}>✕</button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">

            {/* ── Summary table of all changes ── */}
            <div style={{ marginBottom: '20px' }}>
              <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px' }}>Changes to be saved</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                <thead>
                  <tr style={{ background: 'var(--surface-hover, #f9fafb)' }}>
                    {['Field', 'Old Value', 'New Value'].map(h => (
                      <th key={h} style={{ textAlign: 'left', padding: '6px 10px', borderBottom: '1px solid var(--border-color)', fontWeight: 600, fontSize: '12px', color: 'var(--text-muted)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {changedFields.map((change, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td style={{ padding: '6px 10px', fontWeight: 500 }}>{change.field}</td>
                      <td style={{ padding: '6px 10px', color: 'var(--danger, #dc2626)', wordBreak: 'break-word' }}>{change.oldVal || '—'}</td>
                      <td style={{ padding: '6px 10px', color: 'var(--success, #059669)', wordBreak: 'break-word' }}>{change.newVal}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* ── Remark inputs ── */}
            <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '12px' }}>
              Reason for each change <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>(required for audit)</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {changedFields.map((change) => (
                <div key={change.field} className="form-group" style={{ marginBottom: 0 }}>
                  <label style={{ fontWeight: 600 }}>{change.field}</label>
                  <input
                    type="text"
                    placeholder="Enter reasoning…"
                    value={remarks[change.field] || ''}
                    onChange={(e) => setRemarks({ ...remarks, [change.field]: e.target.value })}
                    className="form-input"
                    required
                  />
                </div>
              ))}
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" onClick={onCancel} className="btn btn-secondary" disabled={isSubmitting}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
              {isSubmitting ? 'Saving…' : 'Confirm & Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
