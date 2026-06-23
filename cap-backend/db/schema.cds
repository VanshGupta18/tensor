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
        tenderNo       : String(200);      // extracted tender reference number, used for dedup
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
    content      : LargeBinary;            // raw file bytes stored in HANA
    uploadedBy   : String(100);
    uploadedAt   : Timestamp;
    aiResult     : Composition of one AIResults on aiResult.document = $self;
}

// ─────────────────────────────────────────────────
// AIResults  (output from Python FastAPI)
// ─────────────────────────────────────────────────
entity AIResults : cuid {
    document        : Association to Documents;
    confidenceScore : String(20);
    summary         : String(5000);
    keyTerms        : String(2000);         // JSON array stored as string
    rawResponse     : LargeString;          // full Python response JSON
    pdfContent      : LargeBinary;          // generated PDF synopsis bytes
    processedAt     : Timestamp;
}

// ─────────────────────────────────────────────────
// ChatHistories  (chatbot message log)
// ─────────────────────────────────────────────────
entity ChatHistories : cuid {
    tender    : Association to Tenders;
    sender    : String(10);                 // 'user' | 'bot'
    message   : String(5000);
    timestamp : Timestamp;
}
