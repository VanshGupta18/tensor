import React from 'react';

const CHIP_CLASS = {
  Draft:    'chip chip-draft',
  Reviewed: 'chip chip-reviewed',
  Approved: 'chip chip-approved',
};

export default function StatusBadge({ status }) {
  return (
    <span className={CHIP_CLASS[status] || 'chip chip-draft'}>
      {status || '—'}
    </span>
  );
}
