'use strict';

// Helper: parse any date string → YYYY-MM-DD (HANA DATE format), or null
const parseDate = (str) => {
  if (!str) return null;
  const s = String(str);
  // Already YYYY-MM-DD
  let m = s.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  // DD/MM/YYYY or DD-MM-YYYY (most Indian/European tender formats)
  m = s.match(/(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})/);
  if (m) return `${m[3]}-${m[2].padStart(2,'0')}-${m[1].padStart(2,'0')}`;
  return null;
};

// Format AI money object → "INR 52,546.85 Lakhs"
const fmtMoney = (obj) => {
  if (!obj || !obj.amount) return '';
  const amt = Number(obj.amount).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  const den = obj.denomination && obj.denomination !== 'None' && obj.denomination !== 'null' ? ` ${obj.denomination}` : '';
  return `${obj.currency || 'INR'} ${amt}${den}`;
};

// Format AI date/time object → "09/06/2026  ·  15:00 IST"
const fmtDateTime = (v) => {
  if (!v) return '';
  if (typeof v === 'string') return v;
  const parts = [];
  if (v.date) parts.push(v.date);
  if (v.time) parts.push(`${v.time} ${v.timezone || v.tz || 'IST'}`);
  return parts.join('  ·  ');
};

module.exports = {
  parseDate,
  fmtMoney,
  fmtDateTime
};
