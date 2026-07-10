'use strict';
/**
 * tenderProcessing.js — pure helpers and the processFile core logic.
 *
 * Extracted from service.js so the ~270-line handler becomes thin orchestration
 * and these helpers can be tested in isolation.
 */

const cds = require('@sap/cds');

// ── Pure string helpers ────────────────────────────────────────────────────────

/**
 * Normalize a tender reference number:
 *   - Collapse spaces around / and -
 *   - Strip trailing "VERSION 2 / V-2" suffixes
 *
 * Handles AI inconsistencies like "CE-SPD/ ADB/ 2026-27/ T-13 VERSION- 2"
 * → "CE-SPD/ADB/2026-27/T-13"
 */
function normalizeTenderNo(str) {
  if (!str) return str;
  return str
    .toUpperCase()
    .replace(/\s*([\/\-])\s*/g, '$1')
    .replace(/\s+/g, ' ')
    .replace(/\s+VERSION\s*-?\s*\d+$/i, '')
    .replace(/\s+V\s*-?\s*\d+$/i, '')
    .trim();
}

/**
 * Extract the first integer found in a string, or return null.
 */
function parseVersionStr(s) {
  const m = s && String(s).match(/(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

// ── DB helpers ────────────────────────────────────────────────────────────────

/**
 * Update AI-enriched fields on a Tender row.
 * Tolerates missing columns so schema migrations don't block an upload.
 */
async function applyAIEnrichment(Tenders, id, setObj) {
  try {
    await UPDATE(Tenders).set(setObj).where({ ID: id });
  } catch (err) {
    console.warn('[TenderService] AI field enrichment skipped (run cds deploy):', err.message);
  }
}

/**
 * Store an orphan Document when AI is unavailable or found nothing.
 * Returns the JSON string the processFile action returns to the client.
 */
async function storeOrphanDoc(Documents, { tenderId, filename, mimeType, uploadedBy, uploadedAt }, message) {
  const docId = cds.utils.uuid();
  await INSERT.into(Documents).entries({
    ID: docId, tender_ID: tenderId || null, filename,
    mimeType: mimeType || 'application/octet-stream', uploadedBy, uploadedAt,
  });
  return JSON.stringify({ results: [], message });
}

// ── Main loop ────────────────────────────────────────────────────────────────

/**
 * Process the array of tenders returned by the Python AI service.
 *
 * @param {object} entities  - { Tenders, Documents, AIResults, TenderAudits }
 * @param {object} ctx       - { tenderId, filename, mimeType, uploadedBy, uploadedAt }
 * @param {Array}  pyTenders - array of AI-extracted tender objects
 * @returns {string}         - JSON string { results: [...] }
 */
async function processAITenders(entities, ctx, pyTenders) {
  const { Tenders, Documents, AIResults } = entities;
  const { tenderId, filename, mimeType, uploadedBy, uploadedAt } = ctx;
  const { fmtMoney } = require('./formatters');
  const { parseDate } = require('./formatters');

  const DEDUP_COLS = ['ID', 'title', 'budget', 'deadline', 'location', 'tenderNo'];

  // Pre-compute all tenderNos extracted by AI so we can batch the dedup query.
  const rawTenderNos = pyTenders
    .map(t => normalizeTenderNo((t.tender_overview || t.tender_information)?.reference_no || ''))
    .filter(Boolean);

  // One numeric MAX to determine next TND-NNN ID (string ORDER BY fails at TND-1000).
  const allTenderIds = await SELECT.from(Tenders).columns('ID');
  const maxNum = allTenderIds.reduce((max, r) => {
    const n = parseInt((r.ID || '').replace('TND-', ''), 10);
    return isNaN(n) ? max : Math.max(max, n);
  }, 0);
  let nextTenderNum = maxNum + 1;

  // Two bulk queries instead of up to 2N sequential per-iteration SELECTs.
  const [existingByTenderNoRows, existingByIdRow] = await Promise.all([
    rawTenderNos.length > 0
      ? SELECT.from(Tenders).columns(...DEDUP_COLS).where({ tenderNo: { in: rawTenderNos } })
      : Promise.resolve([]),
    tenderId
      ? SELECT.one.from(Tenders).columns(...DEDUP_COLS).where({ ID: tenderId })
      : Promise.resolve(null),
  ]);

  const tenderNoMap = new Map(existingByTenderNoRows.map(t => [t.tenderNo, t]));

  const results = [];

  for (const aiTender of pyTenders) {
    const tenderOverview = aiTender.tender_overview || aiTender.tender_information || {};
    const keyDates       = tenderOverview.key_dates || aiTender.key_dates || {};

    const rawTenderNo       = tenderOverview.reference_no || '';
    const extractedTenderNo = normalizeTenderNo(rawTenderNo);
    const extractedTitle    = tenderOverview.title || aiTender.summary || 'Untitled Tender';
    const extractedBudget   = fmtMoney(tenderOverview.estimated_cost) || '';
    const extractedDeadline = parseDate(keyDates.bid_submission_deadline?.date);
    const extractedLocation = '';

    const aiEnrichmentSet = {
      issuingAuthority: tenderOverview.issuing_authority  || undefined,
      contractType:     tenderOverview.contract_type      || undefined,
      bidSystem:        tenderOverview.bid_system         || undefined,
      fundingAgency:    tenderOverview.funding_agency     || undefined,
      tenderFee:        fmtMoney(tenderOverview.tender_fee) || undefined,
      budgetCategory:   tenderOverview.budget_category    || undefined,
      contacts:         JSON.stringify(tenderOverview.contacts || []),
    };

    const { tender_information: _ti, summary: _summary, documentHash: _docHash, ...remainingSections } = aiTender;

    const versionFromTenderNo = (() => {
      const m = rawTenderNo.match(/VERSION\s*-?\s*(\d+)/i) || rawTenderNo.match(/\bV\s*-\s*(\d+)\b/i);
      return m ? parseInt(m[1], 10) : null;
    })();
    const extractedVersion = parseVersionStr(tenderOverview.version) || versionFromTenderNo || 1;

    const docId = cds.utils.uuid();

    const existingTender = extractedTenderNo
      ? (tenderNoMap.get(extractedTenderNo) ?? null)
      : (existingByIdRow ?? null);

    let resultTenderId;
    let isNew = false;
    let changedFields = [];
    let pendingPatch = null;

    if (!existingTender) {
      // ── Branch A: new tender ─────────────────────────────────────────────────
      isNew = true;
      resultTenderId = `TND-${String(nextTenderNum).padStart(3, '0')}`;
      nextTenderNum++;

      await cds.db.tx(async (tx) => {
        await tx.run(INSERT.into(Tenders).entries({
          ID: resultTenderId, tenderNo: extractedTenderNo || null,
          version: extractedVersion, title: extractedTitle,
          budget: extractedBudget || 'TBD', deadline: extractedDeadline || null,
          status: 'Draft', location: extractedLocation || '',
          contractor: 'Not Selected', createdBy: uploadedBy,
          lastReviewedBy: '-', lastChangedBy: uploadedBy,
        }));
        await tx.run(INSERT.into(Documents).entries({
          ID: docId, tender_ID: resultTenderId, filename,
          mimeType: mimeType || 'application/octet-stream', uploadedBy, uploadedAt,
          contentHash: aiTender.documentHash || null,
        }));
        await tx.run(INSERT.into(AIResults).entries({
          ID: cds.utils.uuid(), document_ID: docId,
          summary: aiTender.summary || '',
          rawResponse: JSON.stringify(remainingSections),
          processedAt: new Date().toISOString(),
        }));
      });

      await applyAIEnrichment(Tenders, resultTenderId, aiEnrichmentSet);

    } else {
      // ── Branch B: duplicate — return diff for user confirmation ──────────────
      resultTenderId = existingTender.ID;

      const allFields = [
        { field: 'Title',    dbKey: 'title',    newVal: extractedTitle },
        { field: 'Budget',   dbKey: 'budget',   newVal: extractedBudget },
        { field: 'Deadline', dbKey: 'deadline', newVal: extractedDeadline },
        { field: 'Location', dbKey: 'location', newVal: extractedLocation },
      ];

      pendingPatch = { lastChangedBy: uploadedBy };
      for (const { field, dbKey, newVal } of allFields) {
        const dbNorm  = (existingTender[dbKey]  == null) ? '' : String(existingTender[dbKey]).trim();
        const newNorm = (newVal == null)                 ? '' : String(newVal).trim();
        if (newVal && dbNorm !== newNorm) {
          changedFields.push({ field, oldVal: existingTender[dbKey] || '—', newVal });
          pendingPatch[dbKey] = newVal;
        }
      }

      await applyAIEnrichment(Tenders, resultTenderId, aiEnrichmentSet);

      const existingDoc = await SELECT.one.from(Documents).columns('ID')
        .where({ tender_ID: resultTenderId })
        .orderBy({ uploadedAt: 'desc' });

      const docFields = {
        filename, mimeType: mimeType || 'application/octet-stream', uploadedBy, uploadedAt,
        contentHash: aiTender.documentHash || null,
      };
      const resultFields = {
        summary: aiTender.summary || '',
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
        await INSERT.into(Documents).entries({ ID: docId, tender_ID: resultTenderId, ...docFields });
        await INSERT.into(AIResults).entries({ ID: cds.utils.uuid(), document_ID: docId, ...resultFields });
      }
    }

    const requiresConfirmation = !isNew;
    results.push({
      tenderId: resultTenderId,
      tenderNo: extractedTenderNo || '',
      title: extractedTitle,
      isNew,
      changedFields,
      requiresConfirmation,
      pendingPatch: requiresConfirmation ? pendingPatch : null,
      rawJson: aiTender,
      extractedValues: {
        tenderNo:  extractedTenderNo || '',
        title:     extractedTitle    || '',
        budget:    extractedBudget   || '',
        deadline:  extractedDeadline || '',
        location:  extractedLocation || '',
      },
    });
  }

  return JSON.stringify({ results });
}

module.exports = { normalizeTenderNo, parseVersionStr, applyAIEnrichment, storeOrphanDoc, processAITenders };
