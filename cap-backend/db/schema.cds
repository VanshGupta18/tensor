namespace com.tenderflow;

using { cuid, managed } from '@sap/cds/common';

// ─────────────────────────────────────────────────
// Users
// ─────────────────────────────────────────────────
entity Users : cuid {
    username : String(100) not null;
    role     : String(50) default 'user';  // 'admin' | 'user' | 'reviewer'
    createdAt: Timestamp;
}

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
        // AI-extracted fields (populated by processFile, read-only in UI)
        issuingAuthority     : String(500);
        contractType         : String(200);
        bidSystem            : String(200);
        fundingAgency        : String(500);
        tenderFee            : String(100);
        budgetCategory       : String(200);
        publicationDate      : String(100);
        preBidMeeting        : String(200);
        bidSubmissionDeadline: String(200);
        technicalOpening     : String(200);
        financialOpening     : String(200);
        workOrderIssuance    : String(200);
        // Associations
        audits         : Composition of many TenderAudits on audits.tender = $self;
        documents      : Composition of many Documents    on documents.tender = $self;
        chatHistory    : Composition of many ChatHistories on chatHistory.tender = $self;
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
    uploadedBy   : String(100);
    uploadedAt   : Timestamp;
    aiResult     : Composition of one AIResults on aiResult.document = $self;
}

// ─────────────────────────────────────────────────
// AIResults  (output from Python AI service)
// ─────────────────────────────────────────────────
entity AIResults : cuid {
    document        : Association to Documents;
    confidenceScore : String(20);
    summary         : String(5000);
    keyTerms        : String(2000);         // JSON array stored as string
    rawResponse     : LargeString;          // full Python response JSON
    // pdfContent field removed — PDFs generated on demand from rawResponse, never persisted
    processedAt     : Timestamp;
}

// ─────────────────────────────────────────────────
// ChatHistories  (chatbot message log)
// ─────────────────────────────────────────────────
entity ChatHistories : cuid {
    tender    : Association to Tenders;
    sender    : String(10);                 // 'user' | 'bot'
    message   : String(5000);              // inline storage — faster reads, cheaper than LOB
    timestamp : Timestamp;
}
