'use strict';

/**
 * Latest Document's contentHash for a tender — the join key into python-ai-service's
 * Postgres/pgvector chunk store, used to ground chat in the actual source PDF instead
 * of a document-blind assistant. Mirrors the "latest Document by tenderId" lookup
 * already used by the generatePDF action (service.js), factored out since chat now
 * needs the same pattern in two more places (service.js `chat`, chatController.js).
 *
 * Returns "" if there's no tender ID, no processed Document yet, or no contentHash
 * (e.g. AI processing failed) — callers treat that as "answer without grounding".
 */
async function getLatestContentHash(tenderId) {
  if (!tenderId) return '';
  try {
    const doc = await SELECT.one.from('TenderService.Documents')
      .columns('contentHash')
      .where({ tender_ID: tenderId })
      .orderBy({ uploadedAt: 'desc' });
    return doc?.contentHash || '';
  } catch (e) {
    console.error('[documentLookup] failed to fetch contentHash:', e.message);
    return '';
  }
}

module.exports = { getLatestContentHash };
