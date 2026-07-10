/**
 * api/tenderApi.js
 *
 * All Tender-related API calls:
 *   - CRUD on /Tenders
 *   - Audit log via submitAudit action
 *   - Download helper (client-side JSON export)
 */

import api, { callAction } from './client.js';
import { base64ToBlob } from '../utils/fileUtils.js';

// ── Helpers to convert CAP OData shape ↔ React shape ─────────────────────────

/**
 * Map a CAP Tender entity to the internal React shape.
 * CAP stores details as flat columns; React uses a nested `details` object.
 */
function toReactShape(t) {
  return {
    id:             t.ID,
    tenderNo:       t.tenderNo,
    version:        t.version,
    title:          t.title,
    createdBy:      t.createdBy,
    lastReviewedBy: t.lastReviewedBy || '-',
    lastChangedBy:  t.lastChangedBy,
    details: {
      budget:                t.budget,
      deadline:              t.deadline,
      status:                t.status,
      location:              t.location,
      contractor:            t.contractor,
      // AI-extracted fields — everything tender_information contains. key_dates
      // fields are read from AIResults.rawResponse instead (see useTenderDocuments /
      // DetailsScreen's aiData.key_dates) — they're not flattened onto Tenders.
      issuingAuthority: t.issuingAuthority,
      contractType:     t.contractType,
      bidSystem:        t.bidSystem,
      fundingAgency:    t.fundingAgency,
      tenderFee:        t.tenderFee,
      budgetCategory:   t.budgetCategory,
      contacts:         t.contacts,
    },
    remarks: (t.audits || []).map(a => ({
      fieldName: a.fieldName,
      oldVal:    a.oldVal,
      newVal:    a.newVal,
      remark:    a.remark,
      changedBy: a.changedBy,
      changedAt: a.changedAt,
    })),
  };
}

/**
 * Map React form values back to CAP flat structure for PATCH.
 */
function toCapShape(formValues, changedBy) {
  const shape = {
    title:         formValues.title,
    budget:        formValues.budget,
    deadline:      formValues.deadline,
    status:        formValues.status,
    location:      formValues.location,
    contractor:    formValues.contractor,
    lastChangedBy: changedBy,
  };
  const aiKeys = [
    'issuingAuthority', 'contractType', 'bidSystem', 'fundingAgency',
    'tenderFee', 'budgetCategory', 'contacts',
  ];
  for (const k of aiKeys) {
    if (formValues[k] !== undefined) shape[k] = formValues[k] || null;
  }
  return shape;
}

// ── API functions ─────────────────────────────────────────────────────────────

/**
 * Fetch all tenders (expand audit history).
 * Returns array in React shape.
 */
export async function getTenders() {
  const res = await api.get('/Tenders?$expand=audits&$orderby=ID');
  return (res.value || []).map(toReactShape);
}

/**
 * Delete a tender by ID.
 */
export async function deleteTender(id) {
  await api.delete(`/Tenders(ID='${encodeURIComponent(id)}',IsActiveEntity=true)`);
}

/**
 * Update tender fields.
 * Returns refreshed tender in React shape.
 */
export async function updateTender(id, formValues, changedBy) {
  await api.patch(`/Tenders(ID='${encodeURIComponent(id)}',IsActiveEntity=true)`, toCapShape(formValues, changedBy));
  // No follow-up GET — caller reconstructs from cache in onSuccess
}

/**
 * Mark tender as "reviewed" by updating lastReviewedBy.
 */
export async function markReviewed(id, username) {
  await api.patch(`/Tenders(ID='${encodeURIComponent(id)}',IsActiveEntity=true)`, { lastReviewedBy: username });
  // No follow-up GET — mutation's onSuccess reconstructs from cache
}

/**
 * Submit one audit entry for a single field change.
 */
export async function submitAuditEntry({ tenderId, fieldName, oldVal, newVal, remark, changedBy }) {
  return callAction('submitAudit', { tenderId, fieldName, oldVal, newVal, remark, changedBy });
}

/**
 * Submit audit entries for multiple fields changed at once.
 * Returns a Promise that resolves when all entries are posted.
 */
export async function submitAuditBatch(tenderId, changedList, remarksObject, changedBy) {
  const promises = changedList.map(change =>
    submitAuditEntry({
      tenderId,
      fieldName: change.field,
      oldVal:    change.oldVal,
      newVal:    change.newVal,
      remark:    remarksObject[change.field] || 'No remarks provided',
      changedBy,
    })
  );
  return Promise.all(promises);
}

/**
 * Fetch all Documents (with their AIResult) for a given tender.
 * Returns the raw OData value array — callers parse rawResponse as needed.
 */
export async function getTenderDocuments(tenderId) {
  const escapedId = tenderId.replace(/'/g, "''");
  const encoded = encodeURIComponent(`tender_ID eq '${escapedId}'`);
  const res = await api.get(`/Documents?$filter=${encoded}&$expand=aiResult&$orderby=uploadedAt desc`);
  return res.value || [];
}

/**
 * Update the rawResponse of an AIResult via a custom action.
 * Direct OData PATCH fails due to draft key validation on related entities.
 *
 * Stores tenderDoc exactly as given — no wrapper. The pipeline's canonical
 * rawResponse shape is the flat 9-section tender object (matching what
 * python-ai-service/CAP ingestion already stores on first upload); wrapping it in an
 * extra `{ sections: ... }` envelope here used to corrupt the shape on every edit,
 * making DetailsScreen's hydration mistake it for the old legacy array format and
 * collapse all 9 sections into one "Legacy Section" panel.
 */
export async function updateAIResult(id, tenderDoc) {
  return callAction('updateAIResult', {
    id,
    rawResponse: JSON.stringify(tenderDoc),
  });
}

/**
 * Download tender as a formatted PDF synopsis.
 * Calls the CAP generatePDF action which returns a base64-encoded PDF.
 * The base64 string is decoded into a Blob and downloaded as a .pdf file.
 * Falls back to a client-side JSON export if the PDF endpoint fails.
 */
export async function downloadTender(tender) {
  try {
    // callAction returns the OData action result — a base64 string
    const result = await callAction('generatePDF', { tenderId: tender.id });

    // The OData action wraps the return value in { value: "..." }
    const b64 = result?.value ?? result;
    if (!b64 || typeof b64 !== 'string') throw new Error('Empty or invalid PDF data returned');

    const blob = base64ToBlob(b64, 'application/pdf');

    const url = URL.createObjectURL(blob);
    const a   = document.createElement('a');
    a.href     = url;
    a.download = `tender_${tender.tenderNo || tender.id}_synopsis.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

  } catch (err) {
    console.error('PDF download failed, falling back to JSON export:', err.message);
    // Fallback: download as JSON (includes AI-extracted fields so data is not lost)
    const downloadData = {
      tenderId:        tender.id,
      version:         tender.version,
      title:           tender.title,
      createdBy:       tender.createdBy,
      lastReviewedBy:  tender.lastReviewedBy,
      lastChangedBy:   tender.lastChangedBy,
      details:         tender.details,
      remarksHistory:  tender.remarks,
    };
    const jsonString = `data:text/json;charset=utf-8,${encodeURIComponent(JSON.stringify(downloadData, null, 2))}`;
    const a = document.createElement('a');
    a.setAttribute('href', jsonString);
    a.setAttribute('download', `tender_${tender.id}_v${tender.version}.json`);
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Re-throw so the caller (UI) can show a warning that PDF failed
    throw new Error(`PDF generation failed — downloaded as JSON instead. (${err.message})`);
  }
}

