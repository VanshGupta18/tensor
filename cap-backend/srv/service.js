/**
 * TenderService – CAP service handler
 *
 * Responsibilities:
 *   - Postgres CRUD (auto-managed by CAP runtime)
 *   - Version auto-increment on Tender update
 *   - Audit trail writing (via submitAudit action)
 *   - File upload persistence + Python AI forwarding
 *   - Chat message relay (session-only, no DB persistence)
 *
 * Python AI service base URL is configured via env var:
 *   PYTHON_AI_URL  (default: http://localhost:8002)
 */

const cds = require('@sap/cds');
const { processAITenders, storeOrphanDoc } = require('./utils/tenderProcessing');

const axios = require('axios');
const { processFileWithAI, purgeDocumentFromAI, PYTHON_AI_URL } = require('./services/aiService');

async function purgeContentHashIfOrphan(contentHash) {
  if (!contentHash) return null;

  const stillReferenced = await SELECT.one.from(Documents)
    .columns('ID')
    .where({ contentHash });

  if (stillReferenced) {
    console.log(`[purge] hash ${contentHash.slice(0, 12)}… still referenced — skipping`);
    return null;
  }

  const result = await purgeDocumentFromAI(contentHash);
  console.log(`[purge] removed artifacts for ${contentHash.slice(0, 12)}…`, result);
  return result;
}

// ─────────────────────────────────────────────────────────────────────────────
// NOTE: stream-chat express routes are registered in server.js bootstrap,
// not here. cds.on('bootstrap') in service implementations fires after the
// bootstrap event has already occurred, so routes registered here are never
// reached and the client receives 404. See server.js for all custom routes.
// ─────────────────────────────────────────────────────────────────────────────
module.exports = cds.service.impl(async function (srv) {

  const { Tenders, TenderAudits, Documents, AIResults } = srv.entities;


  // ── READ Tenders: per-user data isolation ──────────────────────────────────
  // With dummy/mocked auth (dev) this is a no-op. In production (XSUAA), non-admin
  // users only see tenders they created.
  srv.before('READ', Tenders, (req) => {
    if (cds.env.requires?.auth?.kind === 'mocked') return;
    if (req.user.is('admin')) return;
    req.query.where({ createdBy: req.user.id });
  });

  // ── PATCH Tender: protect PDF-extracted fields ──────────────────────────────
  // version and tenderNo are set by processFile from PDF extraction.
  // Strip them from any direct PATCH so the form auto-saves cannot overwrite them.
  srv.before('UPDATE', Tenders, (req) => {
    delete req.data.version;
    delete req.data.tenderNo;
  });

  // ── DELETE Tender: collect content hashes, purge AI artifacts after DB delete ─
  srv.before('DELETE', Tenders, async (req) => {
    const id = req.data?.ID;
    if (!id) return;

    const docs = await SELECT.from(Documents)
      .columns('contentHash')
      .where({ tender_ID: id });

    req._ = req._ || {};
    req._.purgeHashes = [...new Set(
      docs.map(d => d.contentHash).filter(Boolean)
    )];
  });

  srv.after('DELETE', Tenders, async (req) => {
    const hashes = req._?.purgeHashes || [];
    for (const hash of hashes) {
      try {
        await purgeContentHashIfOrphan(hash);
      } catch (err) {
        console.error(`[TenderService] purge after delete failed for ${hash.slice(0, 12)}…:`, err.message);
      }
    }
  });

  // ── Action: login ────────────────────────────────────────────────────────────
  // Simple credential store — replace with XSUAA in production.
  const USERS = {
    admin   : { password: process.env.ADMIN_PASSWORD    || 'admin',   role: 'admin' },
    reviewer: { password: process.env.REVIEWER_PASSWORD || 'alice',   role: 'reviewer' },
  };

  srv.on('login', async (req) => {
    const { username, password } = req.data;
    const record = USERS[username];
    if (!record || record.password !== password) {
      return req.error(401, 'Invalid username or password');
    }
    return { username, role: record.role };
  });

  // ── Action: submitAudit ──────────────────────────────────────────────────────
  srv.on('submitAudit', async (req) => {
    const { tenderId, fieldName, oldVal, newVal, remark, changedBy } = req.data;

    const exists = await SELECT.one.from(Tenders).columns('ID').where({ ID: tenderId });
    if (!exists) return req.error(404, `Tender ${tenderId} not found`);

    const entry = {
      ID:        cds.utils.uuid(),
      tender_ID: tenderId,
      fieldName,
      oldVal,
      newVal,
      remark:    remark || 'No remarks provided',
      changedBy,
      changedAt: new Date().toISOString()
    };
    await INSERT.into(TenderAudits).entries(entry);
    return entry;
  });

  srv.on('submitAuditBatch', async (req) => {
    const { tenderId, entries, changedBy } = req.data;

    let items;
    try {
      items = JSON.parse(entries);
    } catch (e) {
      return req.error(400, `Invalid JSON: ${e.message}`);
    }
    if (!Array.isArray(items) || items.length === 0) return [];

    const exists = await SELECT.one.from(Tenders).columns('ID').where({ ID: tenderId });
    if (!exists) return req.error(404, `Tender ${tenderId} not found`);

    const changedAt = new Date().toISOString();
    const rows = items.map(({ fieldName, oldVal, newVal, remark }) => ({
      ID:        cds.utils.uuid(),
      tender_ID: tenderId,
      fieldName,
      oldVal,
      newVal,
      remark:    remark || 'No remarks provided',
      changedBy,
      changedAt,
    }));
    await INSERT.into(TenderAudits).entries(rows);
    return rows;
  });

  // ── Action: processFile ──────────────────────────────────────────────────────
  srv.on('processFile', async (req) => {
    const { tenderId, filename, filepath, mimeType } = req.data;
    const uploadedAt = new Date().toISOString();
    const uploadedBy = req.user?.id || 'unknown';

    const { pyTenders, pyError } = await processFileWithAI(filepath, filename, mimeType);

    const fs = require('fs');
    if (filepath && fs.existsSync(filepath)) {
      try { fs.unlinkSync(filepath); } catch (e) { console.error('Failed to clean up temp file', e); }
    }

    const orphanCtx = { tenderId, filename, mimeType, uploadedBy, uploadedAt };
    if (!pyTenders)        return storeOrphanDoc(Documents, orphanCtx, pyError || 'Python AI service unavailable. Document stored.');
    if (!pyTenders.length) return storeOrphanDoc(Documents, orphanCtx, 'No tender information found in the document.');

    return processAITenders(
      { Tenders, Documents, AIResults },
      { tenderId, filename, mimeType, uploadedBy, uploadedAt },
      pyTenders,
    );
  });

  // ── Action: applyTenderUpdate ────────────────────────────────────────────────
  // Called by React after the user confirms a duplicate-update prompt.
  srv.on('applyTenderUpdate', async (req) => {
    const { tenderId, patch, changedFields } = req.data;

    let patchObj, changedFieldsArr;
    try {
      patchObj         = JSON.parse(patch);
      changedFieldsArr = JSON.parse(changedFields);
    } catch (e) {
      return req.error(400, `Invalid JSON: ${e.message}`);
    }
    if (!Array.isArray(changedFieldsArr)) return req.error(400, 'changedFields must be a JSON array');

    const ALLOWED_PATCH_KEYS = ['title', 'budget', 'deadline', 'location', 'lastChangedBy'];
    const safePatch = Object.fromEntries(
      Object.entries(patchObj).filter(([k]) => ALLOWED_PATCH_KEYS.includes(k))
    );

    const tender = await SELECT.one.from(Tenders).where({ ID: tenderId });
    if (!tender) return req.error(404, `Tender ${tenderId} not found`);

    await UPDATE(Tenders).set(safePatch).where({ ID: tenderId });

    // Batch-insert all audit entries in one round-trip
    if (changedFieldsArr.length > 0) {
      await INSERT.into(TenderAudits).entries(
        changedFieldsArr.map(({ field, oldVal, newVal }) => ({
          ID:        cds.utils.uuid(),
          tender_ID: tenderId,
          fieldName: field,
          oldVal,
          newVal,
          remark:    'Updated from PDF upload (user confirmed)',
          changedBy: safePatch.lastChangedBy || 'unknown',
          changedAt: new Date().toISOString(),
        }))
      );
    }

    return JSON.stringify({ success: true, tenderId });
  });

  // ── Action: updateAIResult ───────────────────────────────────────────────────
  srv.on('updateAIResult', async (req) => {
    const { id, rawResponse } = req.data;
    const existing = await SELECT.one.from(AIResults).columns('ID').where({ ID: id });
    if (!existing) return req.error(404, `AIResult ${id} not found`);
    await UPDATE(AIResults).set({ rawResponse }).where({ ID: id });
    return JSON.stringify({ success: true });
  });

  // ── Action: generatePDF ─────────────────────────────────────────────────────
  // Generates a PDF on demand from the stored AI extraction data.
  srv.on('generatePDF', async (req) => {
    const { tenderId } = req.data;
    if (!tenderId) return req.error(400, 'tenderId is required');

    // 1. Find the most recent Document then its AIResult — 2 queries total
    const doc = await SELECT.one.from(Documents)
      .columns('ID')
      .where({ tender_ID: tenderId })
      .orderBy({ uploadedAt: 'desc' });

    if (!doc) {
      return req.error(404, 'No AI-processed data found for this tender. Please upload a PDF first.');
    }

    const aiResult = await SELECT.one.from(AIResults)
      .columns('ID', 'rawResponse', 'summary')
      .where({ document_ID: doc.ID });

    if (!aiResult?.rawResponse) {
      return req.error(404, 'No AI data found for this tender.');
    }

    // 2. Generate PDF fresh every time (always use latest template)
    let parsed = null;
    try {
      parsed = JSON.parse(aiResult.rawResponse);
    } catch { return req.error(500, 'Failed to parse stored AI data'); }

    // Support both old format ({sections:[...]}) and new format ({tenders:[...]})
    const tenderDoc = parsed?.tenders?.[0] ?? parsed ?? {};

    // Overlay the live, user-editable Tenders columns onto tender_overview so the
    // PDF reflects the current edited values rather than the original AI extraction
    // (tender_fee/estimated_cost/key_dates stay as extracted — they have no flat
    // Tenders-column equivalent to overlay from).
    const tenderRow = await SELECT.one.from(Tenders)
      .columns('title', 'tenderNo', 'version', 'issuingAuthority', 'contractType', 'bidSystem', 'fundingAgency', 'budgetCategory', 'contacts')
      .where({ ID: tenderId });
    if (tenderRow) {
      let contacts = [];
      try { contacts = JSON.parse(tenderRow.contacts || '[]'); } catch { /* keep [] */ }
      tenderDoc.tender_overview = {
        ...(tenderDoc.tender_overview || {}),
        title:             tenderRow.title             || tenderDoc.tender_overview?.title,
        reference_no:      tenderRow.tenderNo           || tenderDoc.tender_overview?.reference_no,
        version:           tenderRow.version != null ? String(tenderRow.version) : tenderDoc.tender_overview?.version,
        issuing_authority: tenderRow.issuingAuthority   || tenderDoc.tender_overview?.issuing_authority,
        contract_type:     tenderRow.contractType       || tenderDoc.tender_overview?.contract_type,
        bid_system:        tenderRow.bidSystem          || tenderDoc.tender_overview?.bid_system,
        funding_agency:    tenderRow.fundingAgency      || tenderDoc.tender_overview?.funding_agency,
        budget_category:   tenderRow.budgetCategory     || tenderDoc.tender_overview?.budget_category,
        contacts:          contacts.length > 0 ? contacts : tenderDoc.tender_overview?.contacts,
      };
    }

    let pdfBuffer;
    try {
      const pyRes = await axios.post(`${PYTHON_AI_URL}/generate_pdf`, {
        tender: tenderDoc,
        title: aiResult.summary || 'Tender Synopsis',
      }, { timeout: 30_000, responseType: 'arraybuffer' });
      pdfBuffer = Buffer.from(pyRes.data);
    } catch (err) {
      let detail = err.message;
      if (err.response?.data) {
        try {
          const buf = Buffer.isBuffer(err.response.data) ? err.response.data : Buffer.from(err.response.data);
          const body = JSON.parse(buf.toString('utf8'));
          detail = body?.error || buf.toString('utf8').slice(0, 400);
        } catch { /* keep err.message */ }
      }
      console.error('[TenderService] generatePDF Python error:', detail);
      return req.error(500, `PDF generation failed: ${detail}`);
    }

    return pdfBuffer.toString('base64');
  });

});
