import React, { useState, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import SubmitRemarksModal from './SubmitRemarksModal';
import { useTenderDocuments } from '../hooks/useTender.js';
import { updateAIResult } from '../api/tenderApi.js';
import { fmtDateTime } from '../utils/formatters.js';
import { getPathValue, applyEditsToData } from '../utils/dataUtils.js';
import { SKIP_SECTIONS, SECTION_ORDER, SECTION_LABELS, isSectionReal, renderObjectField, renderSmartSection } from './details/SmartRenderer.jsx';

// tender_information is fully flattened onto Tenders now (see schema.cds) — contacts
// is the one field stored as JSON text rather than its own column.
const parseContacts = raw => {
  if (!raw) return [];
  try { const v = JSON.parse(raw); return Array.isArray(v) ? v : []; } catch { return []; }
};

const TABLE_TH = { padding: '7px 10px', fontSize: '12px', fontWeight: 600, background: 'var(--bg-hover,#f9fafb)', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border-color,#e5e7eb)' };
const TABLE_TD = { padding: '8px 10px', fontSize: '13px', verticalAlign: 'top', borderBottom: '1px solid var(--border-color,#e5e7eb)' };

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

  // tender_information fields — plain editable state, same as the fields above,
  // since this data now lives directly on Tenders rather than inside aiData/rawResponse.
  const [issuingAuthority, setIssuingAuthority] = useState(tender.details.issuingAuthority || '');
  const [contractType,     setContractType]     = useState(tender.details.contractType || '');
  const [bidSystem,        setBidSystem]        = useState(tender.details.bidSystem || '');
  const [fundingAgency,    setFundingAgency]    = useState(tender.details.fundingAgency || '');
  const [tenderFee,        setTenderFee]        = useState(tender.details.tenderFee || '');
  const [budgetCategory,   setBudgetCategory]   = useState(tender.details.budgetCategory || '');
  const [contacts,         setContacts]         = useState(() => parseContacts(tender.details.contacts));

  const [showRemarksModal, setShowRemarksModal] = useState(false);
  const [changedFields,    setChangedFields]    = useState([]);
  const [hasAiInSave,      setHasAiInSave]      = useState(false);

  const handleDownload = () => {
    if (onDownload) {
      onDownload(tender);
    }
  };

  // AI extracted data
  const [aiData,          setAiData]          = useState(null);
  const [aiResultId,      setAiResultId]      = useState(null);
  const [aiEdits,         setAiEdits]         = useState({});   // path → new content

  const queryClient = useQueryClient();
  const { data: documents = [], isLoading: aiLoading } = useTenderDocuments(tender.id);

  useEffect(() => {
    setTitle(tender.title);
    setBudget(tender.details.budget);
    setDeadline(tender.details.deadline);
    setStatus(tender.details.status);
    setLocation(tender.details.location);
    setContractor(tender.details.contractor);
    setIssuingAuthority(tender.details.issuingAuthority || '');
    setContractType(tender.details.contractType || '');
    setBidSystem(tender.details.bidSystem || '');
    setFundingAgency(tender.details.fundingAgency || '');
    setTenderFee(tender.details.tenderFee || '');
    setBudgetCategory(tender.details.budgetCategory || '');
    setContacts(parseContacts(tender.details.contacts));
  }, [tender]);

  // Reset AI state when navigating to a different tender
  useEffect(() => {
    setAiEdits({});
    setAiData(null);
    setAiResultId(null);
  }, [tender?.id]);

  // Hydrate local AI state from documents (skip if user has in-progress edits)
  useEffect(() => {
    if (Object.keys(aiEdits).length > 0) return;
    const docWithAi = documents.find(d => d.aiResult);
    if (docWithAi?.aiResult?.rawResponse) {
      try {
        const parsed = JSON.parse(docWithAi.aiResult.rawResponse);
        let data = null;
        if (parsed.tenders && parsed.tenders.length > 0) {
          data = parsed.tenders[0];
        } else if (Array.isArray(parsed.sections)) {
          data = { legacy_sections: parsed.sections };
        } else if (parsed.sections && typeof parsed.sections === 'object') {
          data = parsed.sections;
        } else {
          data = parsed;
        }
        setAiData(data);
        setAiResultId(docWithAi.aiResult.ID);

        // Fallback: if DB-enriched fields are empty (tender processed before service.js fix),
        // populate them from rawResponse's tender_overview section.
        const ov = data?.tender_overview;
        if (ov && typeof ov === 'object' && ov._status !== 'not_extracted') {
          if (!issuingAuthority && ov.issuing_authority) setIssuingAuthority(ov.issuing_authority);
          if (!contractType     && ov.contract_type)     setContractType(ov.contract_type);
          if (!bidSystem        && ov.bid_system)        setBidSystem(ov.bid_system);
          if (!fundingAgency    && ov.funding_agency)    setFundingAgency(ov.funding_agency);
          if (!budgetCategory   && ov.budget_category)   setBudgetCategory(ov.budget_category);
          if (!tenderFee && ov.tender_fee?.amount) {
            const fee = ov.tender_fee;
            setTenderFee(`${fee.amount} ${fee.currency || ''}`.trim());
          }
          if (contacts.length === 0 && Array.isArray(ov.contacts) && ov.contacts.length > 0) {
            setContacts(ov.contacts);
          }
        }
      } catch {
        setAiData(null);
      }
    }
  }, [documents, aiEdits]);


  const getChangesList = () => {
    const list = [];
    if (title     !== tender.title)             list.push({ field: 'Title',      oldVal: tender.title,             newVal: title });
    if (budget    !== tender.details.budget)    list.push({ field: 'Budget',     oldVal: tender.details.budget,    newVal: budget });
    if (deadline  !== tender.details.deadline)  list.push({ field: 'Deadline',   oldVal: tender.details.deadline,  newVal: deadline });
    if (status    !== tender.details.status)    list.push({ field: 'Status',     oldVal: tender.details.status,    newVal: status });
    if (location  !== tender.details.location)  list.push({ field: 'Location',   oldVal: tender.details.location,  newVal: location });
    if (contractor!== tender.details.contractor)list.push({ field: 'Contractor', oldVal: tender.details.contractor,newVal: contractor });
    const eq = (a, b) => (a || '') === (b || '');
    if (!eq(issuingAuthority, tender.details.issuingAuthority)) list.push({ field: 'Issuing Authority', oldVal: tender.details.issuingAuthority, newVal: issuingAuthority });
    if (!eq(contractType,     tender.details.contractType))     list.push({ field: 'Contract Type',     oldVal: tender.details.contractType,     newVal: contractType });
    if (!eq(bidSystem,        tender.details.bidSystem))        list.push({ field: 'Bid System',        oldVal: tender.details.bidSystem,        newVal: bidSystem });
    if (!eq(fundingAgency,    tender.details.fundingAgency))    list.push({ field: 'Funding Agency',    oldVal: tender.details.fundingAgency,    newVal: fundingAgency });
    if (!eq(tenderFee,        tender.details.tenderFee))        list.push({ field: 'Tender Fee',        oldVal: tender.details.tenderFee,        newVal: tenderFee });
    if (!eq(budgetCategory,   tender.details.budgetCategory))   list.push({ field: 'Budget Category',   oldVal: tender.details.budgetCategory,   newVal: budgetCategory });
    if (JSON.stringify(contacts) !== JSON.stringify(parseContacts(tender.details.contacts))) {
      list.push({ field: 'Contacts', oldVal: tender.details.contacts || '[]', newVal: JSON.stringify(contacts) });
    }
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
    setIssuingAuthority(tender.details.issuingAuthority || '');
    setContractType(tender.details.contractType || '');
    setBidSystem(tender.details.bidSystem || '');
    setFundingAgency(tender.details.fundingAgency || '');
    setTenderFee(tender.details.tenderFee || '');
    setBudgetCategory(tender.details.budgetCategory || '');
    setContacts(parseContacts(tender.details.contacts));
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
      await onSaveChanges(tender.id, {
        title, budget, deadline, status, location, contractor,
        issuingAuthority, contractType, bidSystem, fundingAgency, tenderFee, budgetCategory,
        contacts: JSON.stringify(contacts),
      }, changedFields, remarksObject);
    } catch (err) {
      alert('Save failed: ' + err.message);
      return;
    }

    if (hasAiInSave && aiResultId) {
      try {
        const updatedData = applyEditsToData(aiData, aiEdits);
        // Always persist the flat tenderDoc shape (matching what the AI pipeline
        // originally stores) — no re-wrapping. See updateAIResult() for why.
        await updateAIResult(aiResultId, updatedData);
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

  return (
    <>
      {/* ── Topbar ───────────────────────────────────────────── */}
      <header className="topbar">
        <button onClick={onBack} className="btn btn-ghost" style={{ paddingLeft: 0, gap: 6 }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          Back
        </button>
        <div className="tb-title">
          <h1 className="tb-h1">{tender.tenderNo || tender.id}</h1>
          <div className="tb-crumb">
            Version {tender.version}
            <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
            {tender.details.status}
          </div>
        </div>
        <div className="tb-acts">
          {!isEditing ? (
            <>
              <button onClick={() => setIsEditing(true)} className="btn btn-sec">Edit</button>
              <button className="btn btn-primary" onClick={handleDownload}>
              Download PDF
            </button>
            </>
          ) : (
            <>
              <button onClick={handleCancelEdit} className="btn btn-ghost">Cancel</button>
              <button onClick={handleSubmitClick} className="btn btn-primary">Review & Save</button>
            </>
          )}
        </div>
      </header>

      <div className="page-body">
      <div className="details-page">

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

          {/* Tender Information (fully flattened onto Tenders) — shown in both view
              and edit modes; Key Dates still reads from aiData since key_dates stays
              inside AIResults.rawResponse. */}
          {(() => {
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
            const editField = (key, label, value, setValue) => (
              <div key={key} className="form-group">
                <label>{label}</label>
                <input type="text" value={value} onChange={e => setValue(e.target.value)} className="form-input" />
              </div>
            );

            const tiFields = [
              frozenField('Reference No',      tender.tenderNo),
              frozenField('Issuing Authority', issuingAuthority),
              frozenField('Contract Type',     contractType),
              frozenField('Bid System',        bidSystem),
              frozenField('Funding Agency',    fundingAgency),
              frozenField('Tender Fee',        tenderFee),
              frozenField('Budget Category',   budgetCategory),
            ].filter(Boolean);
            const tiEditFields = [
              frozenField('Reference No', tender.tenderNo), // dedup key — not directly editable here
              editField('issuingAuthority', 'Issuing Authority', issuingAuthority, setIssuingAuthority),
              editField('contractType',     'Contract Type',     contractType,     setContractType),
              editField('bidSystem',        'Bid System',        bidSystem,        setBidSystem),
              editField('fundingAgency',    'Funding Agency',    fundingAgency,    setFundingAgency),
              editField('tenderFee',        'Tender Fee',        tenderFee,        setTenderFee),
              editField('budgetCategory',   'Budget Category',   budgetCategory,   setBudgetCategory),
            ].filter(Boolean);

            // New schema: key_dates is nested inside tender_overview.
            // Old schema: key_dates was a top-level section in rawResponse.
            const kd = aiData?.tender_overview?.key_dates || aiData?.key_dates || {};
            const kdFields = [
              frozenField('Publication Date',        fmtDateTime(kd.publication)),
              frozenField('Pre-Bid Meeting',         fmtDateTime(kd.pre_bid_meeting)),
              frozenField('Bid Submission Deadline', fmtDateTime(kd.bid_submission_deadline)),
              frozenField('Technical Opening',       fmtDateTime(kd.technical_opening)),
              frozenField('Financial Opening',       fmtDateTime(kd.financial_opening)),
              frozenField('Work Order Issuance',     fmtDateTime(kd.work_order_issuance)),
            ].filter(Boolean);

            const hasTI = !!(tender.tenderNo || issuingAuthority || contractType || bidSystem || fundingAgency || tenderFee || budgetCategory);
            const hasKD = isEditing ? !!kd && Object.keys(kd).length > 0 : kdFields.length > 0;
            const hasContacts = isEditing || contacts.length > 0;

            const updateContact = (i, field, value) =>
              setContacts(prev => prev.map((c, idx) => idx === i ? { ...c, [field]: value } : c));
            const removeContact = i => setContacts(prev => prev.filter((_, idx) => idx !== i));
            const addContact = () => setContacts(prev => [...prev, { name: '', role: '', email: '' }]);

            return (
              <>
                {hasTI && (
                  <div style={{ borderTop: '1px solid var(--border-color)', padding: '20px 24px 0' }}>
                    {sectionLabel('Tender Information')}
                    <div className="details-grid">{isEditing ? tiEditFields : tiFields}</div>
                  </div>
                )}
                {hasKD && (
                  <div style={{ borderTop: '1px solid var(--border-color)', padding: '20px 24px 0' }}>
                    {sectionLabel('Key Dates')}
                    {isEditing
                      ? <div style={{ paddingBottom: 16 }}>{renderObjectField(kd, 'key_dates', '', 0, isEditing, aiEdits, setAiEdits)}</div>
                      : <div className="details-grid">{kdFields}</div>
                    }
                  </div>
                )}
                {hasContacts && (
                  <div style={{ borderTop: '1px solid var(--border-color)', padding: '20px 24px' }}>
                    {sectionLabel('Contacts')}
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead>
                        <tr>
                          <th style={TABLE_TH}>Name</th>
                          <th style={TABLE_TH}>Role</th>
                          <th style={TABLE_TH}>Email</th>
                          {isEditing && <th style={{ ...TABLE_TH, width: 90 }} />}
                        </tr>
                      </thead>
                      <tbody>
                        {contacts.map((c, i) => (
                          <tr key={i} style={{ background: i % 2 ? 'var(--bg-hover,#f9fafb)' : undefined }}>
                            {isEditing ? (
                              <>
                                <td style={TABLE_TD}><input type="text" value={c.name  || ''} onChange={e => updateContact(i, 'name',  e.target.value)} className="form-input" /></td>
                                <td style={TABLE_TD}><input type="text" value={c.role  || ''} onChange={e => updateContact(i, 'role',  e.target.value)} className="form-input" /></td>
                                <td style={TABLE_TD}><input type="text" value={c.email || ''} onChange={e => updateContact(i, 'email', e.target.value)} className="form-input" /></td>
                                <td style={TABLE_TD}><button type="button" onClick={() => removeContact(i)} className="btn btn-ghost">Remove</button></td>
                              </>
                            ) : (
                              <>
                                <td style={{ ...TABLE_TD, fontWeight: 600 }}>{c.name || '—'}</td>
                                <td style={TABLE_TD}>{c.role || '—'}</td>
                                <td style={TABLE_TD}>{c.email || '—'}</td>
                              </>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {isEditing && (
                      <button type="button" onClick={addContact} className="btn btn-sec" style={{ marginTop: 10 }}>+ Add Contact</button>
                    )}
                  </div>
                )}
              </>
            );
          })()}

          {/* ── AI accordion — runs inside the same panel ────────────────────── */}
          {aiLoading && (
            <div style={{ borderTop: '1px solid var(--border-color)', padding: '16px 24px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {[1, 2, 3, 4, 5].map((_, i) => (
                <div key={i} style={{
                  height: '48px', borderRadius: '6px',
                  background: 'linear-gradient(90deg, var(--bg-hover) 25%, #e9eaec 50%, var(--bg-hover) 75%)',
                  backgroundSize: '400% 100%',
                  animation: 'shimmer 1.4s ease infinite',
                  animationDelay: `${i * 0.08}s`,
                }} />
              ))}
            </div>
          )}

          {!aiLoading && aiData && (() => {
            const sections = [...Object.entries(aiData)]
              .filter(([k]) => !SKIP_SECTIONS.has(k))
              // technical_bid_documents comes nested inside contract_and_bidding —
              // split it out so it renders as its own section instead of buried inside.
              .flatMap(([k, v]) => {
                if (k === 'contract_and_bidding' && v && typeof v === 'object' && v.technical_bid_documents) {
                  const { technical_bid_documents, ...rest } = v;
                  return [['contract_and_bidding', rest], ['technical_bid_documents', technical_bid_documents]];
                }
                return [[k, v]];
              })
              // Match PDF: only render sections with real extracted content.
              .filter(([, v]) => isSectionReal(v))
              .sort(([a], [b]) => {
                const ai = SECTION_ORDER.indexOf(a), bi = SECTION_ORDER.indexOf(b);
                if (ai === -1 && bi === -1) return 0;
                if (ai === -1) return 1; if (bi === -1) return -1;
                return ai - bi;
              });
            if (sections.length === 0) return null;
            return (
              <div style={{ borderTop: '1px solid var(--border-color)' }}>
                {sections.map(([sectionKey, sectionValue], idx) => {
                  const label = SECTION_LABELS[sectionKey] || sectionKey.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                  return (
                    <div key={idx} style={{ borderTop: idx > 0 ? '1px solid var(--border-color)' : 'none', padding: '20px 24px 0' }}>
                      <p style={{ margin: '0 0 4px', fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</p>
                      {isEditing
                        ? <div style={{ paddingBottom: 16 }}>{renderObjectField(sectionValue, sectionKey, '', 0, isEditing, aiEdits, setAiEdits)}</div>
                        : renderSmartSection(sectionKey, sectionValue)
                      }
                    </div>
                  );
                })}
              </div>
            );
          })()}

          <div className="details-metadata" style={{ borderTop: '1px solid var(--border-color)' }}>
            <div><strong>Created:</strong> {tender.createdBy}</div>
            <div><strong>Reviewed:</strong> {tender.lastReviewedBy}</div>
            <div><strong>Modified:</strong> {tender.lastChangedBy}</div>
          </div>
        </div>

      </div>{/* details-page */}
      </div>{/* page-body */}

      {showRemarksModal && (
        <SubmitRemarksModal tenderNo={tender.tenderNo} changedFields={changedFields} onCancel={() => setShowRemarksModal(false)} onSave={handleSaveFinal} />
      )}
    </>
  );
}
