import React from 'react';

export default function FileResult({ filename, results, message, confirmStates, onConfirm, onReject }) {
  if (!results || results.length === 0) {
    return (
      <div style={{ fontSize: '13px' }}>
        <span style={{ fontWeight: 600 }}>📄 {filename}</span>
        <div style={{ color: 'var(--text-muted)', marginTop: '4px' }}>
          {message || 'No tender information found.'}
        </div>
      </div>
    );
  }

  return (
    <div style={{ fontSize: '13px' }}>
      <div style={{ fontWeight: 600, marginBottom: '8px' }}>📄 {filename}</div>
      {results.map((r, i) => {
        const state = confirmStates?.[i];

        if (r.requiresConfirmation && r.changedFields?.length > 0) {
          return (
            <div key={i} style={{
              padding: '10px 12px', borderRadius: '8px',
              border: '1px solid #fbbf24', background: '#fffbeb', marginBottom: '8px',
            }}>
              <div style={{ fontWeight: 600, color: '#92400e', marginBottom: '4px' }}>
                ⚠️ Duplicate — {r.tenderNo || r.title}
              </div>
              <div style={{ color: '#78350f', marginBottom: '8px', fontSize: '12px' }}>
                Update existing tender with info from this PDF?
              </div>
              {state === 'confirmed' && <div style={{ color: '#065f46', fontWeight: 500 }}>✅ Updated.</div>}
              {state === 'rejected' && <div style={{ color: 'var(--text-muted)' }}>Skipped.</div>}
              {state === 'error' && <div style={{ color: '#dc2626' }}>Update failed.</div>}
              {(!state || state === 'loading') && (
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    onClick={() => onConfirm(i, r.tenderId, r.pendingPatch, r.changedFields)}
                    disabled={state === 'loading'}
                    style={{ padding: '4px 14px', borderRadius: '6px', border: 'none', background: '#059669', color: '#fff', cursor: 'pointer', fontWeight: 600, fontSize: '12px' }}
                  >
                    {state === 'loading' ? 'Updating…' : 'Yes, update'}
                  </button>
                  <button
                    onClick={() => onReject(i)}
                    disabled={state === 'loading'}
                    style={{ padding: '4px 14px', borderRadius: '6px', border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer', fontSize: '12px' }}
                  >
                    Skip
                  </button>
                </div>
              )}
            </div>
          );
        }

        return (
          <div key={i} style={{
            padding: '10px 12px', borderRadius: '8px',
            border: '1px solid #a7f3d0', background: '#f0fdf4', marginBottom: '8px',
          }}>
            <div style={{ fontWeight: 600, color: '#065f46' }}>
              ✅ {r.requiresConfirmation ? 'No changes found' : 'Tender saved'}
            </div>
            <div style={{ color: 'var(--text-muted)', marginTop: '2px' }}>{r.title}</div>
            {r.tenderNo && <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{r.tenderNo}</div>}
          </div>
        );
      })}
    </div>
  );
}
