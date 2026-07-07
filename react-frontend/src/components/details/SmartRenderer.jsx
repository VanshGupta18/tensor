import { fmtMoney, fmtDateTime } from '../../utils/formatters.js';

// Bookkeeping fields that ride alongside the 6 real sections inside rawResponse
// but were never meant to be shown to the user as tender content.
export const SKIP_SECTIONS = new Set([
  'error', 'warnings', 'confidence_score', 'confidenceScore', 'metadata',
  'processing_time', 'chunk_count', 'rawResponse', 'summary', 'keyTerms', 'documentHash',
  // Old schema keys — tender_overview is shown in the details table, key_dates inside it;
  // tender_information / key_dates are old names for the same concept.
  'tender_information', 'key_dates', 'tender_overview',
  // Old section names no longer produced by the pipeline
  'security_and_financials', 'payment_terms', 'contract_conditions',
]);

// Canonical display order matching the 6 extraction groups in step1_schemas.py.
// technical_bid_documents is nested inside contract_and_bidding in the raw payload —
// DetailsScreen splits it out into its own entry before this order is applied so it
// renders as its own section instead of buried inside Contract & Bidding.
export const SECTION_ORDER = [
  'scope_of_work',
  'eligibility_and_qualification',
  'financial_terms',
  'price_variation',
  'contract_and_bidding',
  'technical_bid_documents',
];

export const SECTION_LABELS = {
  scope_of_work:                 'Scope of Work',
  eligibility_and_qualification: 'Eligibility & Qualification',
  financial_terms:               'Financial Terms & Security',
  price_variation:               'Price Variation / Escalation',
  contract_and_bidding:          'Contract & Bidding Conditions',
  technical_bid_documents:       'Technical Bid Documents',
  // Legacy labels for old stored data
  pre_qualification_criteria:    'Pre-Qualification',
  eligibility_criteria:          'Eligibility',
  evaluation_criteria:           'Evaluation',
  financial_bid_documents:       'Financial Docs',
  contract_terms:                'Contract Terms',
  key_terms:                     'Key Terms',
  security_and_financials:       'Security & Financials',
  payment_terms:                 'Payment Terms',
  contract_conditions:           'Contract Conditions',
};

const isMoney    = v => v && typeof v === 'object' && 'amount' in v && 'currency' in v;
const isDateTime = v => v && typeof v === 'object' && 'date' in v && !('amount' in v) && !('criterion' in v);
const isDuration = v => v && typeof v === 'object' && 'duration' in v && 'unit' in v && Object.keys(v).length === 2;
const isLiqDmg   = v => v && typeof v === 'object' && 'percentage_per_week' in v;

export const formatSmart = v => {
  if (v === null || v === undefined || v === '' || v === 'None' || v === 'null') return '';
  if (typeof v === 'boolean') return v ? 'Yes' : 'No';
  if (isMoney(v)) {
    if (!v.amount && v.amount !== 0) return v.note || '';
    return fmtMoney(v);
  }
  if (isDateTime(v)) {
    if (!v.date) return '';
    return fmtDateTime(v);
  }
  if (isDuration(v)) return v.duration ? `${v.duration} ${v.unit}` : '';
  if (isLiqDmg(v)) {
    const p = [];
    if (v.percentage_per_week) p.push(`${v.percentage_per_week}/week`);
    if (v.max_cap_percentage)  p.push(`max cap: ${v.max_cap_percentage}`);
    return p.join(', ');
  }
  if (typeof v !== 'object') return String(v);
  return null;
};

const TH = { padding: '7px 10px', fontSize: '12px', fontWeight: 600, background: 'var(--bg-hover,#f9fafb)', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border-color,#e5e7eb)' };
const TD = { padding: '8px 10px', fontSize: '13px', verticalAlign: 'top', borderBottom: '1px solid var(--border-color,#e5e7eb)' };

export const renderFieldValue = v => {
  const smart = formatSmart(v);
  if (smart !== null) return smart || <span style={{ color: 'var(--text-muted)' }}>—</span>;

  if (Array.isArray(v)) {
    if (v.length === 0) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
    const f = v[0];
    if (typeof f === 'string') return (
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {v.map((s, i) => <li key={i} style={{ paddingBottom: 3, fontSize: '13px' }}>{s}</li>)}
      </ul>
    );
    if (f && 'criterion' in f && 'requirement' in f) return (
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr><th style={{ ...TH, width: '40%' }}>Criterion</th><th style={TH}>Requirement</th></tr></thead>
        <tbody>{v.map((r, i) => (
          <tr key={i} style={{ background: i % 2 ? 'var(--bg-hover,#f9fafb)' : undefined }}>
            <td style={TD}>{r.criterion}</td><td style={TD}>{r.requirement}</td>
          </tr>
        ))}</tbody>
      </table>
    );
    if (f && 'category' in f && 'details' in f) return (
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr><th style={{ ...TH, width: '30%' }}>Category</th><th style={TH}>Details</th></tr></thead>
        <tbody>{v.map((r, i) => (
          <tr key={i} style={{ background: i % 2 ? 'var(--bg-hover,#f9fafb)' : undefined }}>
            <td style={{ ...TD, fontWeight: 500 }}>{r.category}</td><td style={TD}>{r.details}</td>
          </tr>
        ))}</tbody>
      </table>
    );
    if (f && 'stage' in f) return (
      <ol style={{ margin: 0, paddingLeft: 20, fontSize: '13px' }}>
        {v.map((m, i) => <li key={i} style={{ paddingBottom: 4 }}>
          <strong>{m.stage}</strong>{m.percentage ? ` — ${m.percentage}` : ''}{m.description ? `: ${m.description}` : ''}
        </li>)}
      </ol>
    );
    if (f && 'group_name' in f) return (
      <div style={{ fontSize: '13px' }}>
        {v.map((g, i) => (
          <div key={i} style={{ marginBottom: 10 }}>
            {g.group_name && <div style={{ fontWeight: 600, color: 'var(--text-muted)', fontSize: '11px', textTransform: 'uppercase', marginBottom: 4 }}>{g.group_name}</div>}
            <div style={{ paddingLeft: g.group_name ? 8 : 0, whiteSpace: 'pre-wrap' }}>{g.documents}</div>
          </div>
        ))}
      </div>
    );
    if (f && 'type' in f && 'percentage' in f) return (
      <div style={{ fontSize: '13px' }}>
        {v.map((g, i) => <div key={i}>{g.type}: {g.percentage || '—'}</div>)}
      </div>
    );
    if (f && 'grade' in f) return (
      <div style={{ fontSize: '13px' }}>
        {v.map((g, i) => <div key={i}>Grade {g.grade}: {g.percentage || '—'}</div>)}
      </div>
    );
    if (f && 'name' in f) return (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {v.map((c, i) => (
          <div key={i} style={{ border: '1px solid var(--border-color)', borderRadius: 8, padding: '8px 12px', background: 'var(--bg-hover,#f9fafb)', minWidth: 140 }}>
            {c.name && <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: 2 }}>{c.name}</div>}
            {c.role && <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>{c.role}</div>}
            {c.email && <div style={{ color: 'var(--primary)', fontSize: '11px', marginTop: 2 }}>{c.email}</div>}
          </div>
        ))}
      </div>
    );
    return (
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: '13px' }}>
        {v.map((item, i) => <li key={i}>{typeof item === 'object' ? Object.values(item).filter(Boolean).join(' · ') : String(item)}</li>)}
      </ul>
    );
  }

  if (typeof v === 'object' && v !== null) {
    const entries = Object.entries(v).filter(([, val]) => val !== null && val !== undefined && val !== '');
    if (entries.length === 0) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
    if (entries.length === 1 && typeof entries[0][1] !== 'object' && !Array.isArray(entries[0][1])) {
      return <span style={{ fontSize: '13px' }}>{entries[0][1]}</span>;
    }
    if (entries.every(([, val]) => typeof val !== 'object' && !Array.isArray(val))) {
      return (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {entries.map(([k, val]) => (
            <div key={k} style={{ padding: '4px 10px', background: 'var(--bg-hover,#f9fafb)', borderRadius: 6, fontSize: '12px', border: '1px solid var(--border-color)' }}>
              <span style={{ color: 'var(--text-muted)', marginRight: 4 }}>{k.replace(/_/g, ' ')}:</span>
              <span style={{ fontWeight: 500 }}>{val}</span>
            </div>
          ))}
        </div>
      );
    }
    return (
      <div style={{ fontSize: '13px' }}>
        {entries.map(([k, val]) => {
          const s = formatSmart(val);
          return (
            <div key={k} style={{ marginBottom: 8 }}>
              <div style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 600, marginBottom: 4 }}>{k.replace(/_/g, ' ')}</div>
              {s !== null ? <div style={{ whiteSpace: 'pre-wrap' }}>{s || '—'}</div> : renderFieldValue(val)}
            </div>
          );
        })}
      </div>
    );
  }
  return <span style={{ color: 'var(--text-muted)' }}>—</span>;
};

export const renderSmartSection = (sectionKey, sectionValue) => {
  if (sectionKey === 'technical_bid_documents') {
    const docs = sectionValue?.grouped_documents;
    if (!docs || (Array.isArray(docs) && docs.length === 0)) {
      return <div style={{ padding: 16, color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center' }}>No bid documents listed</div>;
    }
    return <div style={{ padding: '12px 16px' }}>{renderFieldValue(docs)}</div>;
  }

  if (sectionKey === 'legacy_sections' && Array.isArray(sectionValue)) {
    return (
      <div style={{ padding: '4px 16px 16px' }}>
        {sectionValue.map((section, si) => (
          <div key={si} style={{ marginBottom: 16 }}>
            <div style={{ fontWeight: 600, fontSize: '14px', padding: '8px 0', borderBottom: '2px solid var(--border-color)' }}>{section.heading}</div>
            {(section.sub_headings || []).map((sub, si2) => (
              <div key={si2} style={{ display: 'flex', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--border-color,#e5e7eb)' }}>
                <span style={{ minWidth: 200, color: 'var(--text-muted)', fontSize: '12px', fontWeight: 500 }}>{sub.heading}</span>
                <span style={{ flex: 1, fontSize: '13px', whiteSpace: 'pre-wrap' }}>{sub.content || '—'}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    );
  }
  if (Array.isArray(sectionValue)) {
    return <div style={{ padding: '12px 16px' }}>{renderFieldValue(sectionValue)}</div>;
  }
  if (typeof sectionValue === 'object' && sectionValue !== null) {
    const entries = Object.entries(sectionValue).filter(([, v]) => {
      if (v === null || v === undefined || v === '' || v === 'None') return false;
      if (Array.isArray(v) && v.length === 0) return false;
      if (typeof v === 'object' && !Array.isArray(v)) {
        const s = formatSmart(v);
        if (s !== null) return s !== '';
        return Object.values(v).some(x => x !== null && x !== undefined && x !== '');
      }
      return true;
    });
    if (entries.length === 0) return (
      <div style={{ padding: 16, color: 'var(--text-muted)', fontSize: '13px', textAlign: 'center' }}>No data extracted</div>
    );
    return (
      <div style={{ padding: '4px 16px 16px' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            {entries.map(([key, val]) => {
              const label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
              const smart = formatSmart(val);
              return (
                <tr key={key} style={{ borderBottom: '1px solid var(--border-color,#e5e7eb)', verticalAlign: 'top' }}>
                  <td style={{ padding: '9px 16px 9px 0', width: 190, minWidth: 150, color: 'var(--text-muted)', fontSize: '12px', fontWeight: 600, whiteSpace: 'nowrap' }}>
                    {label}
                  </td>
                  <td style={{ padding: '9px 0', fontSize: '13px', color: 'var(--text-primary)' }}>
                    {smart !== null ? (smart || <span style={{ color: 'var(--text-muted)' }}>—</span>) : renderFieldValue(val)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }
  return <div style={{ padding: '12px 16px', fontSize: '13px' }}>{String(sectionValue)}</div>;
};

const titleLabel = k => String(k).replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

const HEADING = { fontWeight: 600, color: 'var(--text-muted)', fontSize: '12px', textTransform: 'uppercase', marginBottom: '6px', letterSpacing: '0.03em' };
const SUBLABEL = { fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' };
const INPUT = { width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid var(--edge)', fontSize: '13px', boxSizing: 'border-box' };

const EditableInput = ({ path, value, aiEdits, setAiEdits, multiline, style }) => {
  const current = aiEdits[path] !== undefined ? aiEdits[path] : (value ?? '');
  const onChange = e => setAiEdits(prev => ({ ...prev, [path]: e.target.value }));
  return multiline
    ? <textarea value={current} onChange={onChange} style={{ ...INPUT, ...style, resize: 'vertical', minHeight: 36 }} rows={String(value ?? '').length > 80 ? 3 : 1} />
    : <input type="text" value={current} onChange={onChange} style={{ ...INPUT, ...style }} />;
};

const EditableBoolean = ({ path, value, aiEdits, setAiEdits }) => (
  <select
    value={aiEdits[path] !== undefined ? aiEdits[path] : String(value)}
    onChange={e => setAiEdits(prev => ({ ...prev, [path]: e.target.value }))}
    style={INPUT}
  >
    <option value="true">Yes</option>
    <option value="false">No</option>
  </select>
);

// Editable counterpart to renderFieldValue/renderSmartSection — mirrors the same
// money/date/duration/criterion-table/contact-card layouts instead of falling back to
// a generic recursive key:value tree, which is what made edit mode look like raw JSON.
export const renderObjectField = (value, path, keyName, depth = 0, isEditing, aiEdits, setAiEdits) => {
  if (value === null || value === undefined) return null;

  if (isMoney(value)) {
    return (
      <div key={path} style={{ marginBottom: 12 }}>
        {keyName && <div style={HEADING}>{titleLabel(keyName)}</div>}
        <div style={{ display: 'flex', gap: 10 }}>
          <div style={{ flex: 1 }}>
            <div style={SUBLABEL}>Amount</div>
            <EditableInput path={`${path}.amount`} value={value.amount} aiEdits={aiEdits} setAiEdits={setAiEdits} />
          </div>
          <div style={{ width: 100 }}>
            <div style={SUBLABEL}>Currency</div>
            <EditableInput path={`${path}.currency`} value={value.currency} aiEdits={aiEdits} setAiEdits={setAiEdits} />
          </div>
          {'denomination' in value && (
            <div style={{ width: 130 }}>
              <div style={SUBLABEL}>Denomination</div>
              <EditableInput path={`${path}.denomination`} value={value.denomination} aiEdits={aiEdits} setAiEdits={setAiEdits} />
            </div>
          )}
        </div>
      </div>
    );
  }

  if (isDateTime(value)) {
    return (
      <div key={path} style={{ marginBottom: 12 }}>
        {keyName && <div style={HEADING}>{titleLabel(keyName)}</div>}
        <div style={{ display: 'flex', gap: 10 }}>
          <div style={{ flex: 1 }}>
            <div style={SUBLABEL}>Date</div>
            <EditableInput path={`${path}.date`} value={value.date} aiEdits={aiEdits} setAiEdits={setAiEdits} />
          </div>
          {'time' in value && (
            <div style={{ width: 120 }}>
              <div style={SUBLABEL}>Time</div>
              <EditableInput path={`${path}.time`} value={value.time} aiEdits={aiEdits} setAiEdits={setAiEdits} />
            </div>
          )}
          {'timezone' in value && (
            <div style={{ width: 100 }}>
              <div style={SUBLABEL}>Timezone</div>
              <EditableInput path={`${path}.timezone`} value={value.timezone} aiEdits={aiEdits} setAiEdits={setAiEdits} />
            </div>
          )}
        </div>
      </div>
    );
  }

  if (isDuration(value)) {
    return (
      <div key={path} style={{ marginBottom: 12 }}>
        {keyName && <div style={HEADING}>{titleLabel(keyName)}</div>}
        <div style={{ display: 'flex', gap: 10 }}>
          <div style={{ width: 100 }}>
            <div style={SUBLABEL}>Duration</div>
            <EditableInput path={`${path}.duration`} value={value.duration} aiEdits={aiEdits} setAiEdits={setAiEdits} />
          </div>
          <div style={{ width: 120 }}>
            <div style={SUBLABEL}>Unit</div>
            <EditableInput path={`${path}.unit`} value={value.unit} aiEdits={aiEdits} setAiEdits={setAiEdits} />
          </div>
        </div>
      </div>
    );
  }

  if (isLiqDmg(value)) {
    return (
      <div key={path} style={{ marginBottom: 12 }}>
        {keyName && <div style={HEADING}>{titleLabel(keyName)}</div>}
        <div style={{ display: 'flex', gap: 10 }}>
          <div style={{ flex: 1 }}>
            <div style={SUBLABEL}>% per week</div>
            <EditableInput path={`${path}.percentage_per_week`} value={value.percentage_per_week} aiEdits={aiEdits} setAiEdits={setAiEdits} />
          </div>
          {'max_cap_percentage' in value && (
            <div style={{ flex: 1 }}>
              <div style={SUBLABEL}>Max cap %</div>
              <EditableInput path={`${path}.max_cap_percentage`} value={value.max_cap_percentage} aiEdits={aiEdits} setAiEdits={setAiEdits} />
            </div>
          )}
        </div>
      </div>
    );
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return keyName ? (
        <div key={path} style={{ marginBottom: 12 }}>
          <div style={HEADING}>{titleLabel(keyName)}</div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Empty list</div>
        </div>
      ) : null;
    }
    const first = value[0];

    // criterion/requirement or category/details → editable two-column table, same
    // shape renderFieldValue uses in view mode.
    const pairKeys = (first && typeof first === 'object' && 'criterion' in first && 'requirement' in first) ? ['criterion', 'requirement']
      : (first && typeof first === 'object' && 'category' in first && 'details' in first) ? ['category', 'details']
      : null;
    if (pairKeys) {
      const [k1, k2] = pairKeys;
      return (
        <div key={path} style={{ marginBottom: 12 }}>
          {keyName && <div style={HEADING}>{titleLabel(keyName)}</div>}
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr><th style={{ ...TH, width: '35%' }}>{titleLabel(k1)}</th><th style={TH}>{titleLabel(k2)}</th></tr></thead>
            <tbody>
              {value.map((row, i) => (
                <tr key={i}>
                  <td style={{ ...TD, verticalAlign: 'top' }}><EditableInput path={`${path}.${i}.${k1}`} value={row[k1]} aiEdits={aiEdits} setAiEdits={setAiEdits} multiline /></td>
                  <td style={{ ...TD, verticalAlign: 'top' }}><EditableInput path={`${path}.${i}.${k2}`} value={row[k2]} aiEdits={aiEdits} setAiEdits={setAiEdits} multiline /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }

    // contacts {name, role, email} → editable cards, same layout as view mode
    if (first && typeof first === 'object' && 'name' in first) {
      return (
        <div key={path} style={{ marginBottom: 12 }}>
          {keyName && <div style={HEADING}>{titleLabel(keyName)}</div>}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {value.map((c, i) => (
              <div key={i} style={{ border: '1px solid var(--border-color)', borderRadius: 8, padding: 10, background: 'var(--bg-hover,#f9fafb)', minWidth: 180, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <EditableInput path={`${path}.${i}.name`} value={c.name} aiEdits={aiEdits} setAiEdits={setAiEdits} style={{ fontWeight: 600 }} />
                {'role'  in c && <EditableInput path={`${path}.${i}.role`}  value={c.role}  aiEdits={aiEdits} setAiEdits={setAiEdits} />}
                {'email' in c && <EditableInput path={`${path}.${i}.email`} value={c.email} aiEdits={aiEdits} setAiEdits={setAiEdits} />}
              </div>
            ))}
          </div>
        </div>
      );
    }

    // Plain string/number list → one input per line, no per-item chrome
    if (typeof first === 'string' || typeof first === 'number') {
      return (
        <div key={path} style={{ marginBottom: 12 }}>
          {keyName && <div style={HEADING}>{titleLabel(keyName)}</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {value.map((_, i) => (
              <EditableInput key={i} path={`${path}.${i}`} value={value[i]} aiEdits={aiEdits} setAiEdits={setAiEdits} multiline />
            ))}
          </div>
        </div>
      );
    }

    // Fallback for shapes with no dedicated layout: numbered cards instead of a
    // JSON-tree-style indent guide.
    return (
      <div key={path} style={{ marginBottom: 12 }}>
        {keyName && <div style={HEADING}>{titleLabel(keyName)}</div>}
        {value.map((item, i) => (
          <div key={i} style={{ border: '1px solid var(--border-color)', borderRadius: 8, padding: 12, marginBottom: 8, background: 'var(--bg-hover,#f9fafb)' }}>
            {renderObjectField(item, `${path}.${i}`, null, depth + 1, isEditing, aiEdits, setAiEdits)}
          </div>
        ))}
      </div>
    );
  }

  if (typeof value === 'object') {
    return (
      <div key={path} style={{ marginBottom: 12 }}>
        {keyName && <div style={HEADING}>{titleLabel(keyName)}</div>}
        {Object.entries(value).map(([k, v]) => renderObjectField(v, `${path}.${k}`, k, depth + 1, isEditing, aiEdits, setAiEdits))}
      </div>
    );
  }

  if (typeof value === 'boolean') {
    return (
      <div key={path} style={{ display: 'flex', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--border-color)', alignItems: 'flex-start' }}>
        <div style={{ minWidth: 180, color: 'var(--text-muted)', fontSize: 13, fontWeight: 500, paddingTop: 8 }}>{titleLabel(keyName)}</div>
        <div style={{ flex: 1, fontSize: 13 }}><EditableBoolean path={path} value={value} aiEdits={aiEdits} setAiEdits={setAiEdits} /></div>
      </div>
    );
  }

  // Primitive (string/number)
  return (
    <div key={path} style={{ display: 'flex', gap: 12, padding: '8px 0', borderBottom: '1px solid var(--border-color)', alignItems: 'flex-start' }}>
      <div style={{ minWidth: 180, color: 'var(--text-muted)', fontSize: 13, fontWeight: 500, paddingTop: 8 }}>{titleLabel(keyName)}</div>
      <div style={{ flex: 1, fontSize: 13 }}><EditableInput path={path} value={value} aiEdits={aiEdits} setAiEdits={setAiEdits} multiline /></div>
    </div>
  );
};
