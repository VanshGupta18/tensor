'use strict';

const parseDate = (str) => {
  if (!str) return null;
  const s = String(str);
  let m = s.match(/(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  m = s.match(/(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})/);
  if (m) return `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`;
  return null;
};

const fmtMoney = (obj) => {
  if (!obj || !obj.amount) return '';
  const amt = Number(obj.amount).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  const den = obj.denomination && obj.denomination !== 'None' && obj.denomination !== 'null' ? ` ${obj.denomination}` : '';
  return `${obj.currency || 'INR'} ${amt}${den}`;
};

module.exports = { parseDate, fmtMoney };
