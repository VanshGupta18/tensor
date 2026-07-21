using com.tenderflow as db from '../db/schema';

// ─────────────────────────────────────────────────
// TenderService  – exposed over /odata/v4/tender
// ─────────────────────────────────────────────────
// With dummy auth (dev) all users satisfy 'authenticated-user'.
// In production, switch package.json auth.kind to 'xsuaa' and bind the XSUAA service instance.
@requires: 'authenticated-user'
service TenderService @(path: '/odata/v4/tender') {

    // ── Tender CRUD ──────────────────────────────
    @requires: 'authenticated-user'
    @odata.draft.enabled
    entity Tenders     as projection on db.Tenders;

    // ── Read-only audit log ───────────────────────
    @requires: 'authenticated-user'
    @readonly
    entity TenderAudits as projection on db.TenderAudits;

    // ── Documents ─────────────────────────────────
    entity Documents   as projection on db.Documents;

    // ── AI Results ───────────────────────────────
    entity AIResults   as projection on db.AIResults;

    // ChatHistories projection removed along with the db entity — chat is session-only,
    // never persisted server-side (see db/schema.cds for why).

    // ── Unbound Actions (called as POST RPC) ──────

    /**
     * Authenticate a user against stored credentials.
     * Returns username + role on success or throws 401.
     * Intentionally public (@requires: null) so the login page can call it unauthenticated.
     */
    @(requires: null)
    action login(username: String, password: String) returns {
        username: String;
        role    : String;
    };
    /**
     * Submit an audit entry explicitly from the client.
     * Used after a PATCH on Tenders to store field-level remarks.
     */
    action submitAudit(
        tenderId  : String,
        fieldName : String,
        oldVal    : String,
        newVal    : String,
        remark    : String,
        changedBy : String
    ) returns TenderAudits;

    /** Batch variant — entries is a JSON array of { fieldName, oldVal, newVal, remark }. */
    action submitAuditBatch(
        tenderId  : String,
        entries   : String,
        changedBy : String
    ) returns many TenderAudits;

    /**
     * Forward file to Python AI service, store Document + AIResult.
     * Returns the AIResult JSON for display in the chatbot.
     */
    action processFile(
        tenderId : String,
        filename : String,
        filepath : String,
        mimeType : String
    ) returns String;   // JSON: { results: [...] } — see processFile handler in service.js

    /**
     * Apply a pending duplicate-tender update after user confirmation.
     * patch and changedFields are JSON strings.
     */
    action applyTenderUpdate(
        tenderId     : String,
        patch        : String,
        changedFields: String
    ) returns String;

    /**
     * Update the rawResponse of an AIResult by ID.
     * Uses an action to bypass OData draft key validation on AIResults.
     */
    action updateAIResult(
        id          : String,
        rawResponse : String
    ) returns String;

    /**
     * Generate (or retrieve cached) PDF synopsis for a tender.
     * Returns base64-encoded PDF bytes so it works cleanly over OData JSON.
     */
    action generatePDF(
        tenderId : String
    ) returns String;   // base64-encoded PDF
}
