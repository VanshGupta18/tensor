namespace com.tenderflow;

using { cuid, managed } from '@sap/cds/common';

// ─────────────────────────────────────────────────
// Tenders  (core entity)
// ─────────────────────────────────────────────────
entity Tenders : managed {
    key ID             : String(20);       // e.g. "TND-001"
        @assert.unique
        tenderNo       : String(200);      // extracted tender reference number — unique index for dedup queries
        version        : Integer default 1;
        title          : String(500) not null;
        budget         : String(50);
        deadline       : Date;
        status         : String(50) default 'Draft'; // Draft | Reviewed | Approved
        location       : String(200);
        contractor     : String(200) default 'Not Selected';
        createdBy      : String(100);
        lastReviewedBy : String(100);
        lastChangedBy  : String(100);
        // AI-extracted fields — everything the tender_information section contains,
        // populated by processFile, read-only display + editable here rather than
        // duplicated inside AIResults.rawResponse.
        issuingAuthority     : String(500);
        contractType         : String(200);
        bidSystem            : String(200);
        fundingAgency        : String(500);
        tenderFee            : String(100);
        budgetCategory       : String(200);
        contacts             : LargeString;    // JSON array of {name, role, email}
        // key_dates fields are NOT flattened here (they live in AIResults.rawResponse,
        // one of the 8 remaining sections) — `deadline` above is the one exception,
        // kept as a first-class column because dashboard sort/filter needs a real Date,
        // not just a display value.
        // Associations
        audits         : Composition of many TenderAudits on audits.tender = $self;
        documents      : Composition of many Documents    on documents.tender = $self;
}

// ─────────────────────────────────────────────────
// TenderAudits  (immutable change log)
// ─────────────────────────────────────────────────
entity TenderAudits : cuid {
    tender    : Association to Tenders;
    fieldName : String(100);
    oldVal    : String(1000);
    newVal    : String(1000);
    remark    : String(2000);
    changedBy : String(100);
    changedAt : Timestamp;
}

// ─────────────────────────────────────────────────
// Documents  (uploaded files)
// ─────────────────────────────────────────────────
entity Documents : cuid {
    tender       : Association to Tenders;
    filename     : String(500);
    mimeType     : String(100);
    // content field removed — file bytes forwarded to Python then discarded, never persisted
    // by CAP. Python itself now persists a copy locally (storage/documents/<contentHash>.pdf)
    // for RAG chunk grounding — contentHash is the join key back to that copy and to the
    // Postgres/pgvector chunks indexed under it.
    contentHash  : String(64);
    uploadedBy   : String(100);
    uploadedAt   : Timestamp;
    aiResult     : Composition of one AIResults on aiResult.document = $self;
}

// ─────────────────────────────────────────────────
// AIResults  (output from Python AI service)
// ─────────────────────────────────────────────────
entity AIResults : cuid {
    document        : Association to Documents;
    summary         : String(5000);
    // rawResponse holds only the 8 sections other than tender_information (which is
    // fully flattened onto Tenders above) — key_dates, scope_of_work,
    // eligibility_and_qualification, security_and_financials, payment_terms,
    // price_variation, contract_conditions, technical_bid_documents.
    rawResponse     : LargeString;          // full Python response JSON
    // pdfContent field removed — PDFs generated on demand from rawResponse, never persisted
    // Processing-time/token analytics are no longer persisted — the Analytics screen now
    // polls the Python service's in-memory /analytics/live endpoint in real time instead.
    processedAt     : Timestamp;
}

// ChatHistories entity removed — the frontend never reads persisted chat history back
// (ChatbotPanel only ever shows the current in-memory session), so durable server-side
// storage was pure write-only waste. Chat remains fully functional; only the DB
// persistence side-effect is gone.
