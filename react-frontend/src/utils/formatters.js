export const fmtMoney = (obj) => {
  if (!obj || !obj.amount) return '';
  const amt = Number(obj.amount).toLocaleString('en-IN', { maximumFractionDigits: 2 });
  const den = obj.denomination && obj.denomination !== 'None' && obj.denomination !== 'null' ? ` ${obj.denomination}` : '';
  return `${obj.currency || 'INR'} ${amt}${den}`;
};

export const fmtDateTime = (v) => {
  if (!v) return '';
  if (typeof v === 'string') return v;
  const parts = [];
  if (v.date) parts.push(v.date);
  if (v.time) parts.push(`${v.time} ${v.timezone || v.tz || 'IST'}`);
  return parts.join('  ·  ');
};
