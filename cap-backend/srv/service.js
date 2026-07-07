/**
 * TenderService – CAP service handler
 *
 * Responsibilities:
 *   - HANA CRUD (auto-managed by CAP runtime)
 *   - Version auto-increment on Tender update
 *   - Audit trail writing (via submitAudit action)
 *   - File upload persistence + Python AI forwarding
 *   - Chat message relay + HANA persistence
 *
 * Python AI service base URL is configured via env var:
 *   PYTHON_AI_URL  (default: http://localhost:8000)
 */

const cds = require('@sap/cds');
const { parseDate, fmtMoney, fmtDateTime } = require('./utils/formatters');
const { getLatestContentHash } = require('./utils/documentLookup');

// ── Lazy-load axios ───────────────────────────────────────────────────────────
let axios;
try {
  axios = require('axios');
} catch {
  console.warn('[TenderService] axios not installed – Python AI calls (chat, generatePDF) will fail.');
}
const { processFileWithAI, PYTHON_AI_URL } = require('./services/aiService');

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
    if (cds.env.requires?.auth?.kind === 'dummy') return;
    if (req.user.is('admin')) return;
    req.query.where({ createdBy: req.user.id });
  });

  // ── PATCH Tender: protect PDF-extracted fields ──────────────────────────────
  // version and tenderNo are set by processFile from PDF extraction.
  // Strip them from any direct PATCH so the form auto-saves cannot overwrite them.
  // To bump the version explicitly, call the incrementVersion() bound action instead.
  srv.before('UPDATE', Tenders, (req) => {
    delete req.data.version;
    delete req.data.tenderNo;
  });

  // ── Bound Action: incrementVersion (explicit call) ──────────────────────────
  srv.on('incrementVersion', Tenders, async (req) => {
    const id = req.params[0]?.ID || req.params[0];
    const existing = await SELECT.one.from(Tenders).where({ ID: id });
    if (!existing) return req.error(404, `Tender ${id} not found`);
    const newVersion = (existing.version || 1) + 1;
    // Use cds.db.run to bypass the service before('UPDATE') guard — this is a deliberate
    // explicit version bump, not a form auto-save.
    await cds.db.run(UPDATE(Tenders).set({ version: newVersion }).where({ ID: id }));
    return SELECT.one.from(Tenders).where({ ID: id });
  });

  // ── Action: login ────────────────────────────────────────────────────────────
  // Simple credential store — replace with XSUAA in production.
  const USERS = {
    admin   : { password: process.env.ADMIN_PASSWORD    || 'admin123',   role: 'admin' },
    reviewer: { password: process.env.REVIEWER_PASSWORD || 'review123', role: 'reviewer' },
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

  // ── Action: processFile ──────────────────────────────────────────────────────
  srv.on('processFile', async (req) => {
    const { tenderId, filename, filepath, mimeType } = req.data;
    const uploadedAt = new Date().toISOString();
    const uploadedBy = req.user?.id || 'unknown';

    // ── Helper: apply AI-enriched fields to a Tender row ─────────────────────
    // Defined once and called for both new-tender (Branch A) and duplicate (Branch B).
    // Schema-migration tolerant: if AI columns don't exist yet (pre-deploy), warns and continues.
    const applyAIEnrichment = async (id, setObj) => {
      try {
        await UPDATE(Tenders).set(setObj).where({ ID: id });
      } catch (enrichErr) {
        console.warn('[TenderService] AI field enrichment skipped (run cds deploy):', enrichErr.message);
      }
    };

    // 1. Forward filepath to Python AI service (streams from disk)
    const { pyTenders, pyError } = await processFileWithAI(filepath, filename, mimeType);

    // Clean up temporary file from disk
    const fs = require('fs');
    if (filepath && fs.existsSync(filepath)) {
      try { fs.unlinkSync(filepath); } catch (e) { console.error('Failed to clean up temp file', e); }
    }

    // 2. Early returns: store orphan document when AI is unavailable or found nothing
    const storeOrphanDoc = async (msg) => {
      const docId = cds.utils.uuid();
      await INSERT.into(Documents).entries({
        ID: docId, tender_ID: tenderId || null, filename,
        mimeType: mimeType || 'application/octet-stream', uploadedBy, uploadedAt
      });
      return JSON.stringify({ results: [], message: msg });
    };

    if (!pyTenders)        return storeOrphanDoc(pyError || 'Python AI service unavailable. Document stored.');
    if (!pyTenders.length) return storeOrphanDoc('No tender information found in the document.');

    // ── Pure helpers ──────────────────────────────────────────────────────────



    // Normalize tenderNo: collapse spaces around delimiters, strip trailing version suffixes.
    // Handles AI inconsistencies like "CE-SPD/ ADB/ 2026-27/ T-13 VERSION- 2" → "CE-SPD/ADB/2026-27/T-13"
    const normalizeTenderNo = (str) => {
      if (!str) return str;
      return str
        .toUpperCase()
        .replace(/\s*([\/\-])\s*/g, '$1')        // remove spaces around / and -
        .replace(/\s+/g, ' ')                     // collapse multiple spaces
        .replace(/\s+VERSION\s*-?\s*\d+$/i, '')   // strip trailing "VERSION 2", "VERSION-2", "VERSION- 2"
        .replace(/\s+V\s*-?\s*\d+$/i, '')         // strip trailing "V2", "V-2", "V 2"
        .trim();
    };

    const parseVersionStr = (s) => {
      const m = s && String(s).match(/(\d+)/);
      return m ? parseInt(m[1], 10) : null;
    };

    // 3. Auto-generate next tender ID using numeric MAX to avoid lexicographic sort bug.
    //    String ordering makes 'TND-999' > 'TND-1000', so ORDER BY ID DESC fails at 1000 tenders.
    const allTenderIds = await SELECT.from(Tenders).columns('ID');
    const maxNum = allTenderIds.reduce((max, r) => {
      const n = parseInt((r.ID || '').replace('TND-', ''), 10);
      return isNaN(n) ? max : Math.max(max, n);
    }, 0);
    let nextTenderNum = maxNum + 1;

    const DEDUP_COLS = ['ID', 'title', 'budget', 'deadline', 'location', 'tenderNo'];

    // 4. Batch dedup queries — two bulk queries before the loop instead of up to 2N
    //    sequential per-iteration SELECTs. Results resolved via Map in the loop below.
    const rawTenderNos = pyTenders
      .map(t => normalizeTenderNo((t.tender_overview || t.tender_information)?.reference_no || ''))
      .filter(Boolean);

    const [existingByTenderNoRows, existingByIdRow] = await Promise.all([
      rawTenderNos.length > 0
        ? SELECT.from(Tenders).columns(...DEDUP_COLS).where({ tenderNo: { in: rawTenderNos } })
        : Promise.resolve([]),
      tenderId
        ? SELECT.one.from(Tenders).columns(...DEDUP_COLS).where({ ID: tenderId })
        : Promise.resolve(null),
    ]);

    const tenderNoMap = new Map(existingByTenderNoRows.map(t => [t.tenderNo, t]));

    // 5. Process each tender returned by AI
    const results = [];

    for (const aiTender of pyTenders) {
      // Extract key fields — new 6-section schema uses tender_overview (not tender_information)
      const tenderOverview = aiTender.tender_overview || aiTender.tender_information || {};
      const keyDates        = tenderOverview.key_dates || aiTender.key_dates || {};

      const rawTenderNo         = tenderOverview.reference_no || '';
      const extractedTenderNo   = normalizeTenderNo(rawTenderNo);
      const extractedTitle      = tenderOverview.title || aiTender.summary || 'Untitled Tender';
      const extractedBudget     = fmtMoney(tenderOverview.estimated_cost) || '';
      const extractedDeadline   = parseDate(keyDates.bid_submission_deadline?.date);
      const extractedLocation   = '';  // no AI source available

      // AI-enriched fields — sourced from tender_overview (new) with fallback to tender_information (old).
      const aiEnrichmentSet = {
        issuingAuthority: tenderOverview.issuing_authority    || undefined,
        contractType:     tenderOverview.contract_type        || undefined,
        bidSystem:        tenderOverview.bid_system           || undefined,
        fundingAgency:    tenderOverview.funding_agency       || undefined,
        tenderFee:        fmtMoney(tenderOverview.tender_fee) || undefined,
        budgetCategory:   tenderOverview.budget_category      || undefined,
        contacts:         JSON.stringify(tenderOverview.contacts || []),
      };

      // rawResponse keeps tender_overview (title/tender-info/key_dates/contacts, with
      // tender_fee & estimated_cost as {amount,currency} objects) alongside the other
      // 5 AI sections — the flattened copy on Tenders above is a display/edit
      // convenience, but PDF regeneration and the details-screen Key Dates panel both
      // need the original nested shape, which the flattened string columns can't
      // losslessly reconstruct. summary/documentHash already have dedicated columns
      // (AIResults.summary, Documents.contentHash) — no reason to duplicate those two.
      const { tender_information: _ti, summary: _summary, documentHash: _docHash, ...remainingSections } = aiTender;

      const versionFromTenderNo = (() => {
        const m = rawTenderNo.match(/VERSION\s*-?\s*(\d+)/i) || rawTenderNo.match(/\bV\s*-\s*(\d+)\b/i);
        return m ? parseInt(m[1], 10) : null;
      })();
      const extractedVersion = parseVersionStr(tenderOverview.version) || versionFromTenderNo || 1;

      // Save document ID (used in both branches)
      const docId = cds.utils.uuid();

      // Resolve existing tender from pre-fetched batch results (no per-iteration SELECTs).
      // When the PDF has a reference number, ONLY match by that number.
      // existingByIdRow is a fallback ONLY when no reference number was extracted (e.g. scanned/unstructured PDF).
      const existingTender = extractedTenderNo
        ? (tenderNoMap.get(extractedTenderNo) ?? null)
        : (existingByIdRow ?? null);

      let resultTenderId;
      let isNew = false;
      let changedFields = [];
      let pendingPatch = null;

      if (!existingTender) {
        // ── Branch A: genuinely new tender (no match by tenderNo OR passed ID) ─
        isNew = true;
        resultTenderId = `TND-${String(nextTenderNum).padStart(3, '0')}`;
        nextTenderNum++;

        // Wrap Tender + Document + AIResult in a single transaction so a failure
        // in any step rolls back the whole record — prevents orphaned Draft tenders.
        await cds.db.tx(async (tx) => {
          await tx.run(INSERT.into(Tenders).entries({
            ID:             resultTenderId,
            tenderNo:       extractedTenderNo || null,
            version:        extractedVersion,
            title:          extractedTitle,
            budget:         extractedBudget  || 'TBD',
            deadline:       extractedDeadline || null,
            status:         'Draft',
            location:       extractedLocation || '',
            contractor:     'Not Selected',
            createdBy:      uploadedBy,
            lastReviewedBy: '-',
            lastChangedBy:  uploadedBy,
          }));
          await tx.run(INSERT.into(Documents).entries({
            ID: docId, tender_ID: resultTenderId, filename,
            mimeType: mimeType || 'application/octet-stream', uploadedBy, uploadedAt,
            contentHash: aiTender.documentHash || null,
          }));
          await tx.run(INSERT.into(AIResults).entries({
            ID:              cds.utils.uuid(),
            document_ID:     docId,
            summary:         aiTender.summary || '',
            rawResponse:     JSON.stringify(remainingSections),
            processedAt:     new Date().toISOString(),
          }));
        });

        // AI enrichment runs after the atomic insert — schema-migration tolerant,
        // so a missing column doesn't roll back the already-committed Tender/Document/AIResult.
        await applyAIEnrichment(resultTenderId, aiEnrichmentSet);

      } else {
        // ── Branch B: duplicate found — always ask user to confirm ────────────
        resultTenderId = existingTender.ID;

        // Show all extracted fields (existing vs new) so user can decide
        const allFields = [
          { field: 'Title',    dbKey: 'title',    newVal: extractedTitle },
          { field: 'Budget',   dbKey: 'budget',   newVal: extractedBudget },
          { field: 'Deadline', dbKey: 'deadline', newVal: extractedDeadline },
          { field: 'Location', dbKey: 'location', newVal: extractedLocation },
        ];

        pendingPatch = { lastChangedBy: uploadedBy };
        for (const { field, dbKey, newVal } of allFields) {
          const dbValNormalized = (existingTender[dbKey] === null || existingTender[dbKey] === undefined) ? '' : String(existingTender[dbKey]).trim();
          const newValNormalized = (newVal === null || newVal === undefined) ? '' : String(newVal).trim();

          if (newVal && dbValNormalized !== newValNormalized) {
            changedFields.push({ field, oldVal: existingTender[dbKey] || '—', newVal });
            pendingPatch[dbKey] = newVal;
          }
        }

        // Do NOT update core fields in DB — return requiresConfirmation so React asks the user first.
        // Always silently update AI-enriched fields (no user confirmation needed).
        await applyAIEnrichment(resultTenderId, aiEnrichmentSet);

        // Update the existing Document + AIResult in place rather than accumulating a
        // new pair on every re-upload — re-processing the same tender shouldn't grow
        // record count unbounded. (TenderAudits is untouched — RemarksModal expects
        // that log to keep accumulating.)
        const existingDoc = await SELECT.one.from(Documents).columns('ID')
          .where({ tender_ID: resultTenderId })
          .orderBy({ uploadedAt: 'desc' });

        const docFields = {
          filename, mimeType: mimeType || 'application/octet-stream', uploadedBy, uploadedAt,
          contentHash: aiTender.documentHash || null,
        };
        const resultFields = {
          summary:     aiTender.summary || '',
          rawResponse: JSON.stringify(remainingSections),
          processedAt: new Date().toISOString(),
        };

        if (existingDoc) {
          await UPDATE(Documents).set(docFields).where({ ID: existingDoc.ID });
          const existingResult = await SELECT.one.from(AIResults).columns('ID').where({ document_ID: existingDoc.ID });
          if (existingResult) {
            await UPDATE(AIResults).set(resultFields).where({ ID: existingResult.ID });
          } else {
            await INSERT.into(AIResults).entries({ ID: cds.utils.uuid(), document_ID: existingDoc.ID, ...resultFields });
          }
        } else {
          // No prior Document for this tender (edge case) — nothing to update in place yet.
          await INSERT.into(Documents).entries({ ID: docId, tender_ID: resultTenderId, ...docFields });
          await INSERT.into(AIResults).entries({ ID: cds.utils.uuid(), document_ID: docId, ...resultFields });
        }
      }

      const requiresConfirmation = !isNew;
      results.push({
        tenderId:             resultTenderId,
        tenderNo:             extractedTenderNo || '',
        title:                extractedTitle,
        isNew,
        changedFields,
        requiresConfirmation,
        pendingPatch:         requiresConfirmation ? pendingPatch : null,
        rawJson:              aiTender,
        extractedValues: {
          tenderNo:  extractedTenderNo || '',
          title:     extractedTitle    || '',
          budget:    extractedBudget   || '',
          deadline:  extractedDeadline || '',
          location:  extractedLocation || '',
        }
      });
    }

    // 6. Return results array to React
    return JSON.stringify({ results });
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

  // ── Action: chat ──────────────────────────────────────────────────────────────
  // Session-only — no ChatHistories persistence. The frontend never reads chat
  // history back from the server (ChatbotPanel only shows the current in-memory
  // session), so durably storing every message was pure write-only overhead.
  srv.on('chat', async (req) => {
    const { tenderId, message } = req.data;
    const reqUser = req.user?.id || 'user';

    let botReply = '[AI service unavailable] Your message was received.';

    let pythonTenderRef = tenderId;
    if (tenderId) {
      try {
        const tender = await SELECT.one.from('TenderService.Tenders').columns('tenderNo').where({ ID: tenderId });
        if (tender && tender.tenderNo) {
          pythonTenderRef = tender.tenderNo;
        }
      } catch (e) {
        console.error('[TenderService] failed to fetch tenderNo for chat:', e.message);
      }
    }
    const contentHash = await getLatestContentHash(tenderId);

    if (axios) {
      try {
        const r = await axios.post(`${PYTHON_AI_URL}/response`, { message, tenderId: pythonTenderRef, user: reqUser, contentHash }, { timeout: 60_000 });
        botReply = r.data?.reply || r.data?.response || JSON.stringify(r.data);
      } catch (err) {
        console.error('[TenderService] Python chat error:', err.message);
        botReply = `[AI Error] ${err.message}. Your message was received.`;
      }
    }

    return botReply;
  });

  // ── Action: generatePDF ─────────────────────────────────────────────────────
  // Returns the stored PDF from HANA as a base64 string.
  // If the PDF was never generated (e.g. seeded data), regenerates it on the fly
  // and persists it for next time.
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
    if (!axios) return req.error(503, 'axios not installed');

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

  // ── Action: correctTenderVersion ─────────────────────────────────────────────
  // One-time correction for tenders whose version was corrupted by the old
  // auto-increment-on-every-PATCH bug. Uses cds.db.run to bypass the PATCH guard.
  srv.on('correctTenderVersion', async (req) => {
    const { tenderId, version } = req.data;
    if (!tenderId || !version || version < 1) return req.error(400, 'tenderId and a positive version are required');
    const existing = await SELECT.one.from(Tenders).columns('ID').where({ ID: tenderId });
    if (!existing) return req.error(404, `Tender ${tenderId} not found`);
    await cds.db.run(UPDATE(Tenders).set({ version }).where({ ID: tenderId }));
    return JSON.stringify({ success: true, tenderId, version });
  });

  // ── Action: getAIResultDetail ────────────────────────────────────────────────
  // Fetch the full AIResult including rawResponse (LargeString).
  // Intentionally separate from the OData entity projection so list queries stay lightweight.
  srv.on('getAIResultDetail', async (req) => {
    const { id } = req.data;
    const result = await SELECT.one.from(AIResults).where({ ID: id });
    if (!result) return req.error(404, `AIResult ${id} not found`);
    return result;
  });

});
