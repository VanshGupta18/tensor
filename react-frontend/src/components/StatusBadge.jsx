import React from 'react';

const STATUS_STYLES = {
  Draft:    { background: '#fef9c3', color: '#92400e', border: '1px solid #fde68a' },
  Reviewed: { background: '#dbeafe', color: '#1e40af', border: '1px solid #bfdbfe' },
  Approved: { background: '#d1fae5', color: '#065f46', border: '1px solid #a7f3d0' },
};

export default function StatusBadge({ status }) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 10px',
      borderRadius: '99px',
      fontSize: '12px',
      fontWeight: 600,
      ...(STATUS_STYLES[status] || { background: '#f3f4f6', color: '#374151', border: '1px solid #e5e7eb' }),
    }}>
      {status || '—'}
    </span>
  );
}
