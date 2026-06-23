using com.tenderflow as db from '../db/schema';

// ─────────────────────────────────────────────────
// TenderService  – exposed over /odata/v4/tender
// ─────────────────────────────────────────────────
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
     */
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
}
