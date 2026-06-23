/**
 * api/tenderApi.js
 *
 * All Tender-related API calls:
 *   - CRUD on /Tenders
 *   - Audit log via submitAudit action
 *   - Download helper (client-side JSON export)
 */

import api, { callAction } from './client.js';

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
      budget:     t.budget,
      deadline:   t.deadline,
      status:     t.status,
      location:   t.location,
      contractor: t.contractor,
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
  return {
    title:          formValues.title,
    budget:         formValues.budget,
    deadline:       formValues.deadline,
    status:         formValues.status,
    location:       formValues.location,
    contractor:     formValues.contractor,
    lastChangedBy:  changedBy,
  };
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
 * Fetch a single tender by ID.
 */
export async function getTenderById(id) {
  const t = await api.get(`/Tenders('${encodeURIComponent(id)}')?$expand=audits`);
  return toReactShape(t);
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
  await api.patch(`/Tenders('${encodeURIComponent(id)}')`, toCapShape(formValues, changedBy));
  return getTenderById(id);
}

/**
 * Mark tender as "reviewed" by updating lastReviewedBy.
 */
export async function markReviewed(id, username) {
  await api.patch(`/Tenders('${encodeURIComponent(id)}')`, { lastReviewedBy: username });
  return getTenderById(id);
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
  const encoded = encodeURIComponent(`tender_ID eq '${tenderId}'`);
  const res = await api.get(`/Documents?$filter=${encoded}&$expand=aiResult&$orderby=uploadedAt desc`);
  return res.value || [];
}

/**
 * Update the rawResponse of an AIResult via a custom action.
 * Direct OData PATCH fails due to draft key validation on related entities.
 */
export async function updateAIResult(id, sections) {
  return callAction('updateAIResult', {
    id,
    rawResponse: JSON.stringify({ sections }),
  });
}

/**
 * Client-side JSON download (no API call needed).
 * Identical to the existing mock implementation.
 */
export function downloadTender(tender) {
  const downloadData = {
    tenderId:      tender.id,
    version:       tender.version,
    title:         tender.title,
    createdBy:     tender.createdBy,
    lastReviewedBy:tender.lastReviewedBy,
    lastChangedBy: tender.lastChangedBy,
    details:       tender.details,
    remarksHistory:tender.remarks,
  };
  const jsonString = `data:text/json;charset=utf-8,${encodeURIComponent(JSON.stringify(downloadData, null, 2))}`;
  const a = document.createElement('a');
  a.setAttribute('href', jsonString);
  a.setAttribute('download', `tender_${tender.id}_v${tender.version}.json`);
  document.body.appendChild(a);
  a.click();
  a.remove();
}
