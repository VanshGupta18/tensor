import React, { useState, useEffect } from 'react';
import SubmitRemarksModal from './SubmitRemarksModal';
import { getTenderDocuments, updateAIResult } from '../api/tenderApi.js';

export default function DetailsScreen({
  tender,
  initialIsEditing,
  onBack,
  onSaveChanges,
  onOpenChat,
  onDownload,
  onDelete,
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
  const [aiSections,      setAiSections]      = useState([]);
  const [aiResultId,      setAiResultId]      = useState(null);
  const [aiLoading,       setAiLoading]       = useState(false);
  const [aiEdits,         setAiEdits]         = useState({});   // path → new content
  const [expandedSection, setExpandedSection] = useState(null);

  useEffect(() => {
    setTitle(tender.title);
    setBudget(tender.details.budget);
    setDeadline(tender.details.deadline);
    setStatus(tender.details.status);
    setLocation(tender.details.location);
    setContractor(tender.details.contractor);
  }, [tender]);

  // Load AI result for this tender on mount
  useEffect(() => {
    let cancelled = false;
    async function loadAiData() {
      setAiLoading(true);
      try {
        const docs = await getTenderDocuments(tender.id);
        if (cancelled) return;
        // Use the most recent document that has an aiResult
        const docWithAi = docs.find(d => d.aiResult);
        if (docWithAi?.aiResult?.rawResponse) {
          try {
            const parsed = JSON.parse(docWithAi.aiResult.rawResponse);
            setAiSections(parsed.sections || []);
            setAiResultId(docWithAi.aiResult.ID);
          } catch {
            setAiSections([]);
          }
        }
      } catch {
        // AI data unavailable — silent fail
      } finally {
        if (!cancelled) setAiLoading(false);
      }
    }
    loadAiData();
    return () => { cancelled = true; };
  }, [tender.id]);

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

  // Walk aiSections + aiEdits to produce a flat list of actually-changed leaf fields
  const getAiChangesList = () => {
    const changes = [];
    const walk = (subs, prefix, parentName) => {
      if (!subs) return;
      subs.forEach((sh, i) => {
        const key = prefix + i;
        const name = (parentName ? parentName + ' › ' : '') + sh.heading.replace(/_/g, ' ');
        if (sh.sub_headings && sh.sub_headings.length > 0) {
          walk(sh.sub_headings, key + '-', name);
        } else if (aiEdits[key] !== undefined && aiEdits[key] !== (sh.content || '')) {
          changes.push({ field: name, oldVal: sh.content || '—', newVal: aiEdits[key] });
        }
      });
    };
    aiSections.forEach((section, idx) => {
      const sectionName = section.heading.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
      walk(section.sub_headings, `${idx}-`, sectionName);
    });
    return changes;
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setAiEdits({});
    // reset fields back to current tender values
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

  const handleSaveFinal = async (remarksObject) => {
    try {
      await onSaveChanges(tender.id, { title, budget, deadline, status, location, contractor }, changedFields, remarksObject);
    } catch (err) {
      alert('Save failed: ' + err.message);
      return;
    }

    // Persist AI section data if any AI fields were changed
    if (hasAiInSave && aiResultId) {
      try {
        const updatedSections = applyEditsToSections(aiSections);
        await updateAIResult(aiResultId, updatedSections);
        setAiSections(updatedSections);
        setAiEdits({});
      } catch (err) {
        alert('Changes saved but failed to persist AI data: ' + err.message);
      }
    }

    setShowRemarksModal(false);
    setIsEditing(false);
  };

  // ── Apply in-progress edits back onto sections for save ─────────────────────
  const applyEditsToSections = (sections) =>
    sections.map((section, sIdx) => ({
      ...section,
      sub_headings: applyEditsToSubs(section.sub_headings, sIdx + '-'),
    }));

  const applyEditsToSubs = (subs, prefix) => {
    if (!subs) return subs;
    return subs.map((sh, i) => {
      const key = prefix + i;
      if (sh.sub_headings && sh.sub_headings.length > 0) {
        return { ...sh, sub_headings: applyEditsToSubs(sh.sub_headings, key + '-') };
      }
      return { ...sh, content: aiEdits[key] !== undefined ? aiEdits[key] : sh.content };
    });
  };

  // ── Render sub-headings (read or edit mode) ───────────────────────────────
  const renderSubHeadings = (subHeadings, depth = 0, prefix = '') => {
    if (!subHeadings || subHeadings.length === 0) return null;
    return (
      <div style={{ paddingLeft: depth * 16 }}>
        {subHeadings.map((sh, i) => {
          const key = prefix + i;
          return (
            <div key={i} style={{ marginBottom: '8px' }}>
              {sh.sub_headings && sh.sub_headings.length > 0 ? (
                <>
                  <div style={{ fontWeight: 600, color: 'var(--text-muted)', fontSize: '12px', textTransform: 'uppercase', marginBottom: '4px' }}>
                    {sh.heading.replace(/_/g, ' ')}
                  </div>
                  {renderSubHeadings(sh.sub_headings, depth + 1, key + '-')}
                </>
              ) : (
                <div style={{ display: 'flex', gap: '12px', padding: '6px 0', borderBottom: '1px solid var(--border-color)', alignItems: 'flex-start' }}>
                  <div style={{ minWidth: '180px', color: 'var(--text-muted)', fontSize: '13px', fontWeight: 500, paddingTop: isEditing ? '8px' : 0 }}>
                    {sh.heading.replace(/_/g, ' ')}
                  </div>
                  <div style={{ flex: 1, fontSize: '13px', wordBreak: 'break-word' }}>
                    {isEditing ? (
                      <textarea
                        value={aiEdits[key] !== undefined ? aiEdits[key] : (sh.content || '')}
                        onChange={e => setAiEdits(prev => ({ ...prev, [key]: e.target.value }))}
                        style={{
                          width: '100%', minHeight: '60px', padding: '6px 8px',
                          border: '1px solid var(--border-color)', borderRadius: '6px',
                          fontSize: '13px', fontFamily: 'inherit', resize: 'vertical',
                          boxSizing: 'border-box', background: 'var(--bg-page)',
                        }}
                      />
                    ) : (
                      aiEdits[key] !== undefined ? aiEdits[key] : (sh.content || '—')
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };

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
                {onDelete && (
                  <button onClick={() => onDelete(tender)} className="btn btn-danger">Delete</button>
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
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
              Loading AI extracted data…
            </div>
          )}

          {!aiLoading && aiSections.length === 0 && (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)' }}>
              No AI processed documents found for this tender. Upload a PDF via the Chatbot to extract data.
            </div>
          )}

          {!aiLoading && aiSections.length > 0 && (
            <div style={{ padding: '16px 24px' }}>
              {aiSections.map((section, idx) => {
                const isOpen = expandedSection === idx;
                return (
                  <div key={idx} style={{ marginBottom: '8px', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                    <button
                      onClick={() => setExpandedSection(isOpen ? null : idx)}
                      style={{
                        width: '100%', textAlign: 'left', padding: '12px 16px',
                        background: isOpen ? 'var(--surface-hover, #f9fafb)' : 'transparent',
                        border: 'none', cursor: 'pointer', display: 'flex',
                        justifyContent: 'space-between', alignItems: 'center',
                        fontWeight: 600, fontSize: '14px',
                      }}
                    >
                      <span>{section.heading.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>
                      <span style={{ color: 'var(--text-muted)' }}>{isOpen ? '▲' : '▼'}</span>
                    </button>
                    {isOpen && (
                      <div style={{ padding: '12px 16px', background: 'var(--surface, #fff)' }}>
                        {section.content && (
                          <p style={{ margin: '0 0 8px', fontSize: '13px' }}>{section.content}</p>
                        )}
                        {renderSubHeadings(section.sub_headings, 0, `${idx}-`)}
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
