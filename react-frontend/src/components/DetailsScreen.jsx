import React, { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import SubmitRemarksModal from './SubmitRemarksModal';
import { useTenderDocuments } from '../hooks/useTender.js';
import { updateAIResult } from '../api/tenderApi.js';

export default function DetailsScreen({
  tender,
  initialIsEditing,
  onBack,
  onSaveChanges,
  onOpenChat,
  onDownload,
}) {
  const [isEditing,   setIsEditing]   = useState(initialIsEditing);
  const [title,       setTitle]       = useState(tender.title);
  const [budget,      setBudget]      = useState(tender.details.budget);
  const [deadline,    setDeadline]    = useState(tender.details.deadline);
  const [status,      setStatus]      = useState(tender.details.status);
  const [location,    setLocation]    = useState(tender.details.location);
  const [contractor,  setContractor]  = useState(tender.details.contractor);

  const [showRemarksModal, setShowRemarksModal] = useState(false);
  const [changedFields,    setChangedFields]    = useState([]);
  const [hasAiInSave,      setHasAiInSave]      = useState(false);

  // AI extracted data
  const [aiData,          setAiData]          = useState(null);
  const [aiResultId,      setAiResultId]      = useState(null);
  const [aiEdits,         setAiEdits]         = useState({});   // path → new content
  const [expandedSection, setExpandedSection] = useState(null);

  const queryClient = useQueryClient();
  const { data: documents = [], isLoading: aiLoading } = useTenderDocuments(tender.id);

  useEffect(() => {
    setTitle(tender.title);
    setBudget(tender.details.budget);
    setDeadline(tender.details.deadline);
    setStatus(tender.details.status);
    setLocation(tender.details.location);
    setContractor(tender.details.contractor);
  }, [tender]);

  // Hydrate local AI state
  useEffect(() => {
    if (Object.keys(aiEdits).length > 0) return;
    const docWithAi = documents.find(d => d.aiResult);
    if (docWithAi?.aiResult?.rawResponse) {
      try {
        const parsed = JSON.parse(docWithAi.aiResult.rawResponse);
        if (parsed.tenders && parsed.tenders.length > 0) {
          setAiData(parsed.tenders[0]);
        } else if (parsed.sections) {
          setAiData({ legacy_sections: parsed.sections });
        } else {
          setAiData(parsed);
        }
        setAiResultId(docWithAi.aiResult.ID);
      } catch {
        setAiData(null);
      }
    }
  }, [documents, aiEdits]);

  const getPathValue = (obj, path) => {
    return path.split('.').reduce((acc, part) => acc && acc[part], obj);
  };

  const getChangesList = () => {
    const list = [];
    if (title     !== tender.title)             list.push({ field: 'Title',      oldVal: tender.title,             newVal: title });
    if (budget    !== tender.details.budget)    list.push({ field: 'Budget',     oldVal: tender.details.budget,    newVal: budget });
    if (deadline  !== tender.details.deadline)  list.push({ field: 'Deadline',   oldVal: tender.details.deadline,  newVal: deadline });
    if (status    !== tender.details.status)    list.push({ field: 'Status',     oldVal: tender.details.status,    newVal: status });
    if (location  !== tender.details.location)  list.push({ field: 'Location',   oldVal: tender.details.location,  newVal: location });
    if (contractor!== tender.details.contractor)list.push({ field: 'Contractor', oldVal: tender.details.contractor,newVal: contractor });
    return list;
  };

  const getAiChangesList = () => {
    const changes = [];
    Object.keys(aiEdits).forEach(path => {
      const oldVal = getPathValue(aiData, path);
      changes.push({ 
        field: path.replace(/\./g, ' › ').replace(/_/g, ' '), 
        oldVal: oldVal !== undefined && oldVal !== null ? String(oldVal) : '—', 
        newVal: aiEdits[path] 
      });
    });
    return changes;
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setAiEdits({});
    setTitle(tender.title);
    setBudget(tender.details.budget);
    setDeadline(tender.details.deadline);
    setStatus(tender.details.status);
    setLocation(tender.details.location);
    setContractor(tender.details.contractor);
  };

  const handleSubmitClick = () => {
    const fieldChanges = getChangesList();
    const aiChanges    = getAiChangesList();
    const allChanges   = [...fieldChanges, ...aiChanges];

    if (allChanges.length === 0) {
      alert('No changes were made.');
      setIsEditing(false);
      return;
    }

    setChangedFields(allChanges);
    setHasAiInSave(aiChanges.length > 0);
    setShowRemarksModal(true);
  };

  const applyEditsToData = (data, edits) => {
    const newData = JSON.parse(JSON.stringify(data));
    Object.keys(edits).forEach(path => {
      const parts = path.split('.');
      const last = parts.pop();
      let current = newData;
      parts.forEach(part => {
        if (current[part] === undefined) current[part] = {};
        current = current[part];
      });
      let val = edits[path];
      if (typeof current[last] === 'number' && !isNaN(Number(val))) val = Number(val);
      if (typeof current[last] === 'boolean') val = val === 'true';
      current[last] = val;
    });
    return newData;
  };

  const handleSaveFinal = async (remarksObject) => {
    try {
      await onSaveChanges(tender.id, { title, budget, deadline, status, location, contractor }, changedFields, remarksObject);
    } catch (err) {
      alert('Save failed: ' + err.message);
      return;
    }

    if (hasAiInSave && aiResultId) {
      try {
        const updatedData = applyEditsToData(aiData, aiEdits);
        
        const docWithAi = documents.find(d => d.aiResult);
        let payloadToSave = updatedData;
        if (docWithAi?.aiResult?.rawResponse) {
            const parsed = JSON.parse(docWithAi.aiResult.rawResponse);
            if (parsed.tenders && parsed.tenders.length > 0) {
                parsed.tenders[0] = updatedData;
                payloadToSave = parsed;
            } else if (parsed.sections) {
                payloadToSave = { sections: updatedData.legacy_sections };
            }
        }
        
        await updateAIResult(aiResultId, payloadToSave);
        setAiData(updatedData);
        setAiEdits({});
        queryClient.invalidateQueries({ queryKey: ['tender', tender.id, 'documents'] });
      } catch (err) {
        alert('Changes saved but failed to persist AI data: ' + err.message);
      }
    }

    setShowRemarksModal(false);
    setIsEditing(false);
  };

  const renderObjectField = (value, path, keyName, depth = 0) => {
    if (value === null || value === undefined) return null;

    if (Array.isArray(value)) {
      return (
        <div key={path} style={{ marginBottom: '12px', paddingLeft: depth === 0 ? 0 : 16 }}>
          {keyName && (
             <div style={{ fontWeight: 600, color: 'var(--text-muted)', fontSize: '12px', textTransform: 'uppercase', marginBottom: '4px' }}>
               {String(keyName).replace(/_/g, ' ')}
             </div>
          )}
          {value.length === 0 && <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Empty list</div>}
          {value.map((item, i) => (
             <div key={i} style={{ borderLeft: '2px solid var(--border-color)', paddingLeft: '12px', marginBottom: '8px' }}>
                {renderObjectField(item, `${path}.${i}`, `Item ${i+1}`, depth + 1)}
             </div>
          ))}
        </div>
      );
    }

    if (typeof value === 'object') {
      return (
        <div key={path} style={{ marginBottom: '12px', paddingLeft: depth === 0 ? 0 : 16 }}>
          {keyName && (
            <div style={{ fontWeight: 600, color: 'var(--text-muted)', fontSize: '12px', textTransform: 'uppercase', marginBottom: '4px' }}>
              {String(keyName).replace(/_/g, ' ')}
            </div>
          )}
          {Object.entries(value).map(([k, v]) => renderObjectField(v, `${path}.${k}`, k, depth + 1))}
        </div>
      );
    }

    // Primitive
    return (
      <div key={path} style={{ display: 'flex', gap: '12px', padding: '6px 0', borderBottom: '1px solid var(--border-color)', alignItems: 'flex-start', paddingLeft: depth === 0 ? 0 : 16 }}>
        <div style={{ minWidth: '180px', color: 'var(--text-muted)', fontSize: '13px', fontWeight: 500, paddingTop: isEditing ? '8px' : 0 }}>
          {String(keyName).replace(/_/g, ' ')}
        </div>
        <div style={{ flex: 1, fontSize: '13px', wordBreak: 'break-word' }}>
          {isEditing ? (
            <textarea
              value={aiEdits[path] !== undefined ? aiEdits[path] : String(value)}
              onChange={e => setAiEdits(prev => ({ ...prev, [path]: e.target.value }))}
              style={{
                width: '100%', minHeight: '40px', padding: '6px 8px',
                border: '1px solid var(--border-color)', borderRadius: '6px',
                fontSize: '13px', fontFamily: 'inherit', resize: 'vertical',
                boxSizing: 'border-box', background: 'var(--bg-page)',
              }}
            />
          ) : (
             aiEdits[path] !== undefined ? String(aiEdits[path]) : String(value)
          )}
        </div>
      </div>
    );
  };

  // ── Smart view helpers (view-mode only) ────────────────────────────────────
  const SECTION_LABELS = {
    tender_information:          'Tender Information',
    key_dates:                   'Key Dates',
    scope_of_work:               'Scope of Work',
    eligibility_and_qualification: 'Eligibility & Qualification',
    security_and_financials:     'Security & Financials',
    payment_terms:               'Payment Terms',
    price_variation:             'Price Variation',
    contract_conditions:         'Contract Conditions',
    technical_bid_documents:     'Technical Bid Documents',
    legacy_sections:             'Extracted Data',
  };
  const SECTION_ORDER = Object.keys(SECTION_LABELS);
  // Sections suppressed from the accordion (shown elsewhere or removed entirely)
  const SKIP_SECTIONS = new Set(['tender_information', 'key_dates', 'confidence_score', 'summary', 'key_terms']);

  const isMoney    = v => v && typeof v === 'object' && 'amount' in v && 'currency' in v;
  const isDateTime = v => v && typeof v === 'object' && 'date' in v && !('amount' in v) && !('criterion' in v);
  const isDuration = v => v && typeof v === 'object' && 'duration' in v && 'unit' in v && Object.keys(v).length === 2;
  const isLiqDmg   = v => v && typeof v === 'object' && 'percentage_per_week' in v;

  const formatSmart = v => {
    if (v === null || v === undefined || v === '' || v === 'None' || v === 'null') return '';
    if (typeof v === 'boolean') return v ? 'Yes' : 'No';
    if (isMoney(v)) {
      if (!v.amount && v.amount !== 0) return v.note || '';
      const amt = Number(v.amount).toLocaleString('en-IN', { maximumFractionDigits: 2 });
      const den = v.denomination && v.denomination !== 'None' && v.denomination !== 'null' ? ` ${v.denomination}` : '';
      return `${v.currency || 'INR'} ${amt}${den}`;
    }
    if (isDateTime(v)) {
      if (!v.date) return '';
      if (!v.time) return v.date;
      const tz = v.timezone || v.tz || 'IST';
      return `${v.date}  ·  ${v.time} ${tz}`;
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

  const renderFieldValue = v => {
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

  const renderSmartSection = (sectionKey, sectionValue) => {
    // Technical bid documents — only show grouped_documents list
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
  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <div className="dashboard-wrapper">
      <main className="main-content details-page">
        <button onClick={onBack} className="btn btn-ghost" style={{ marginBottom: '24px', paddingLeft: 0 }}>
          ← Back to Dashboard
        </button>

        <div className="details-header">
          <div className="details-title-group">
            <h2>{tender.tenderNo || tender.id}</h2>
            <p>Version {tender.version} • Current Status: {tender.details.status}</p>
          </div>
          <div className="nav-actions">
            {!isEditing ? (
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <button onClick={() => setIsEditing(true)} className="btn btn-secondary">Edit</button>
                {onDownload && (
                  <button onClick={() => onDownload(tender)} className="btn btn-secondary">Download</button>
                )}
              </div>
            ) : (
              <>
                <button onClick={handleCancelEdit} className="btn btn-ghost">Cancel</button>
                <button onClick={handleSubmitClick} className="btn btn-primary">Review & Save</button>
              </>
            )}
          </div>
        </div>

        {/* ── Editable Tender Fields ───────────────────────────────────────── */}
        <div className="panel">
          <div className="details-grid">
            <div className="form-group">
              <label>Tender Title</label>
              {isEditing
                ? <input type="text" value={title} onChange={e => setTitle(e.target.value)} className="form-input" />
                : <div className="form-input frozen" style={{ whiteSpace: 'normal', wordBreak: 'break-word', height: 'auto', minHeight: '38px' }}>{title}</div>}
            </div>
            <div className="form-group">
              <label>Budget Allocation</label>
              {isEditing
                ? <input type="text" value={budget} onChange={e => setBudget(e.target.value)} className="form-input" />
                : <div className="form-input frozen" style={{ whiteSpace: 'normal', wordBreak: 'break-word', height: 'auto', minHeight: '38px' }}>{budget}</div>}
            </div>
            <div className="form-group">
              <label>Deadline</label>
              <input type="date" value={deadline} onChange={e => setDeadline(e.target.value)} className={`form-input ${!isEditing ? 'frozen' : ''}`} disabled={!isEditing} />
            </div>
            <div className="form-group">
              <label>Lifecycle Status</label>
              {isEditing ? (
                <select value={status} onChange={e => setStatus(e.target.value)} className="form-input">
                  <option value="Draft">Draft</option>
                  <option value="Reviewed">Reviewed</option>
                  <option value="Approved">Approved</option>
                </select>
              ) : (
                <div className="form-input frozen" style={{ whiteSpace: 'normal', wordBreak: 'break-word', height: 'auto', minHeight: '38px' }}>{status}</div>
              )}
            </div>
            <div className="form-group">
              <label>Location</label>
              {isEditing
                ? <input type="text" value={location} onChange={e => setLocation(e.target.value)} className="form-input" />
                : <div className="form-input frozen" style={{ whiteSpace: 'normal', wordBreak: 'break-word', height: 'auto', minHeight: '38px' }}>{location}</div>}
            </div>
            <div className="form-group">
              <label>Assigned Contractor</label>
              {isEditing
                ? <input type="text" value={contractor} onChange={e => setContractor(e.target.value)} className="form-input" />
                : <div className="form-input frozen" style={{ whiteSpace: 'normal', wordBreak: 'break-word', height: 'auto', minHeight: '38px' }}>{contractor}</div>}
            </div>
          </div>

          <div className="details-metadata">
            <div><strong>Created:</strong> {tender.createdBy}</div>
            <div><strong>Reviewed:</strong> {tender.lastReviewedBy}</div>
            <div><strong>Modified:</strong> {tender.lastChangedBy}</div>
          </div>

          {/* AI-extracted fields — read from DB (tender.details), same grid as above */}
          {!isEditing && (() => {
            const d = tender.details;
            const sectionLabel = (text) => (
              <p style={{ margin: '0 0 14px', fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{text}</p>
            );
            const frozenField = (label, value) => !value ? null : (
              <div key={label} className="form-group">
                <label>{label}</label>
                <div className="form-input frozen" style={{ whiteSpace: 'normal', wordBreak: 'break-word', height: 'auto', minHeight: '38px' }}>
                  {value}
                </div>
              </div>
            );
            const tiFields = [
              frozenField('Reference No',      tender.tenderNo),
              frozenField('Issuing Authority', d.issuingAuthority),
              frozenField('Contract Type',     d.contractType),
              frozenField('Bid System',        d.bidSystem),
              frozenField('Funding Agency',    d.fundingAgency),
              frozenField('Tender Fee',        d.tenderFee),
              frozenField('Budget Category',   d.budgetCategory),
            ].filter(Boolean);
            const kdFields = [
              frozenField('Publication Date',        d.publicationDate),
              frozenField('Pre-Bid Meeting',         d.preBidMeeting),
              frozenField('Bid Submission Deadline', d.bidSubmissionDeadline),
              frozenField('Technical Opening',       d.technicalOpening),
              frozenField('Financial Opening',       d.financialOpening),
              frozenField('Work Order Issuance',     d.workOrderIssuance),
            ].filter(Boolean);
            const contacts = aiData?.tender_information?.contacts || [];
            if (tiFields.length === 0 && kdFields.length === 0 && contacts.length === 0) return null;
            return (
              <>
                {tiFields.length > 0 && (
                  <div style={{ borderTop: '1px solid var(--border-color)', padding: '20px 24px 0' }}>
                    {sectionLabel('Tender Information')}
                    <div className="details-grid">{tiFields}</div>
                  </div>
                )}
                {kdFields.length > 0 && (
                  <div style={{ borderTop: '1px solid var(--border-color)', padding: '20px 24px 0' }}>
                    {sectionLabel('Key Dates')}
                    <div className="details-grid">{kdFields}</div>
                  </div>
                )}
                {contacts.length > 0 && (
                  <div style={{ borderTop: '1px solid var(--border-color)', padding: '20px 24px' }}>
                    {sectionLabel('Contacts')}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                      {contacts.map((c, i) => (
                        <div key={i} style={{ border: '1px solid var(--border-color)', borderRadius: 8, padding: '10px 14px', background: 'var(--bg-hover,#f9fafb)', minWidth: 160 }}>
                          {c.name  && <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: 2 }}>{c.name}</div>}
                          {c.role  && <div style={{ color: 'var(--text-muted)', fontSize: '12px' }}>{c.role}</div>}
                          {c.email && <div style={{ color: 'var(--primary)', fontSize: '11px', marginTop: 3 }}>{c.email}</div>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            );
          })()}
        </div>

        {/* ── Tender Data ──────────────────────────────────────────────────── */}
        <div className="panel" style={{ marginTop: '24px' }}>
          <div style={{ padding: '20px 24px', borderBottom: '1px solid var(--border-color)' }}>
            <h3 style={{ margin: 0 }}>Tender Data</h3>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: 'var(--text-muted)' }}>
              Structured data extracted from uploaded PDF documents.
            </p>
          </div>

          {aiLoading && (
            <div style={{ padding: '16px 24px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {[180, 140, 160, 120, 150].map((w, i) => (
                <div key={i} style={{
                  height: '44px', borderRadius: '8px',
                  background: 'linear-gradient(90deg, var(--bg-hover) 25%, #e9eaec 50%, var(--bg-hover) 75%)',
                  backgroundSize: '400% 100%',
                  animation: 'shimmer 1.4s ease infinite',
                  animationDelay: `${i * 0.08}s`,
                  maxWidth: `${w * 4}px`,
                  width: '100%',
                }} />
              ))}
            </div>
          )}

          {!aiLoading && (!aiData || Object.keys(aiData).length === 0) && (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
              No AI processed documents found for this tender. Upload a PDF via the Chatbot to extract data.
            </div>
          )}

          {!aiLoading && aiData && Object.keys(aiData).length > 0 && (
            <div style={{ padding: '16px 24px' }}>
              {[...Object.entries(aiData)]
                .filter(([sectionKey]) => !SKIP_SECTIONS.has(sectionKey))
                .sort(([a], [b]) => {
                  const ai = SECTION_ORDER.indexOf(a), bi = SECTION_ORDER.indexOf(b);
                  if (ai === -1 && bi === -1) return 0;
                  if (ai === -1) return 1;
                  if (bi === -1) return -1;
                  return ai - bi;
                })
                .map(([sectionKey, sectionValue], idx) => {
                  const isOpen = expandedSection === idx;
                  const label = SECTION_LABELS[sectionKey] || sectionKey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                  return (
                    <div key={idx} style={{ marginBottom: '8px', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                      <button
                        onClick={() => setExpandedSection(isOpen ? null : idx)}
                        style={{
                          width: '100%', textAlign: 'left', padding: '12px 16px',
                          background: isOpen ? 'var(--surface-hover,#f9fafb)' : 'transparent',
                          border: 'none', cursor: 'pointer', display: 'flex',
                          justifyContent: 'space-between', alignItems: 'center',
                          fontWeight: 600, fontSize: '14px',
                        }}
                      >
                        <span>{label}</span>
                        <span style={{ color: 'var(--text-muted)' }}>{isOpen ? '▲' : '▼'}</span>
                      </button>
                      {isOpen && (
                        <div style={{ background: 'var(--surface,#fff)' }}>
                          {isEditing
                            ? <div style={{ padding: '12px 16px' }}>{renderObjectField(sectionValue, sectionKey, '', 0)}</div>
                            : renderSmartSection(sectionKey, sectionValue)
                          }
                        </div>
                      )}
                    </div>
                  );
                })}
            </div>
          )}
        </div>
      </main>

      {showRemarksModal && (
        <SubmitRemarksModal tenderNo={tender.tenderNo} changedFields={changedFields} onCancel={() => setShowRemarksModal(false)} onSave={handleSaveFinal} />
      )}
    </div>
  );
}
