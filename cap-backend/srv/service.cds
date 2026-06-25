using com.tenderflow as db from '../db/schema';

// ─────────────────────────────────────────────────
// TenderService  – exposed over /odata/v4/tender
// ─────────────────────────────────────────────────
// With dummy auth (dev) all users satisfy 'authenticated-user'.
// In production, switch package.json auth.kind to 'xsuaa' and bind the XSUAA service instance.
@requires: 'authenticated-user'
service TenderService @(path: '/odata/v4/tender') {

    // ── Tender CRUD ──────────────────────────────
    @odata.draft.enabled
    entity Tenders     as projection on db.Tenders
        actions {
            // Convenience bound action: bump version and return new tender
            action incrementVersion() returns Tenders;
        };

    // ── Read-only audit log ───────────────────────
    @readonly
    entity TenderAudits as projection on db.TenderAudits;

    // ── Documents ─────────────────────────────────
    entity Documents   as projection on db.Documents;

    // ── AI Results ───────────────────────────────
    entity AIResults   as projection on db.AIResults;

    // ── Chat History ─────────────────────────────
    entity ChatHistories as projection on db.ChatHistories;

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

    /**
     * Forward file to Python AI service, store Document + AIResult.
     * Returns the AIResult JSON for display in the chatbot.
     */
    action processFile(
        tenderId : String,
        filename : String,
        content  : LargeBinary,
        mimeType : String
    ) returns String;   // JSON: { confidenceScore, summary, keyTerms }

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
     * Forward a chat message to the Python AI service.
     * Persist the conversation and return the AI reply.
     */
    action chat(
        tenderId : String,
        message  : String,
        sender   : String
    ) returns String;   // the bot's reply text

    /**
     * Generate (or retrieve cached) PDF synopsis for a tender.
     * Returns base64-encoded PDF bytes so it works cleanly over OData JSON.
     */
    action generatePDF(
        tenderId : String
    ) returns String;   // base64-encoded PDF

    /**
     * Fetch full AIResult detail including rawResponse (LargeString).
     * Intentionally a separate action so list queries on AIResults stay lightweight.
     */
    action getAIResultDetail(
        id : String
    ) returns AIResults;

    /**
     * Correct a tender's version to the value extracted from its source PDF.
     * Use this once to fix stale versions left by the old auto-increment bug.
     */
    action correctTenderVersion(
        tenderId : String,
        version  : Integer
    ) returns String;
}
