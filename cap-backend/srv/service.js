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

// ── Lazy-load axios (added via npm install) ───────────────────────────────────
let axios;
try {
  axios = require('axios');
} catch {
  console.warn('[TenderService] axios not installed – Python AI calls will fail.');
}

const PYTHON_AI_URL = process.env.PYTHON_AI_URL || 'http://localhost:8000';

// ─────────────────────────────────────────────────────────────────────────────
module.exports = cds.service.impl(async function (srv) {

  const { Tenders, TenderAudits, Documents, AIResults, ChatHistories } = srv.entities;

  // ── Seed initial data (SQLite / HANA) ──────────────────────────────────────
  cds.on('served', async () => {
    const count = await SELECT.one.from(Tenders).columns('count(*) as n');
    if (count && Number(count.n) === 0) {

      // ── 1. Seed Tenders ────────────────────────────────────────────────────
      await INSERT.into(Tenders).rows([
        {
          ID: 'TND-001', tenderNo: 'MTL/MMRC/2026/T-01', version: 1,
          title: 'Construction of Metro Line 4A – Elevated Corridor',
          budget: '₹12,000 Crore', deadline: '2026-12-31', status: 'Draft',
          location: 'Mumbai, Maharashtra', contractor: 'Not Selected',
          createdBy: 'Alice', lastReviewedBy: '-', lastChangedBy: 'Alice'
        },
        {
          ID: 'TND-002', tenderNo: 'SGPD/BER/2026/T-03', version: 3,
          title: 'Smart Grids Power Distribution Upgrade – Zone 4',
          budget: '€38,000,000', deadline: '2026-10-15', status: 'Reviewed',
          location: 'Berlin, Germany', contractor: 'Siemens AG',
          createdBy: 'David', lastReviewedBy: 'Emily', lastChangedBy: 'Emily'
        },
        {
          ID: 'TND-003', tenderNo: 'WTF/AUS/2026/T-07', version: 2,
          title: 'Waste Treatment Facility Upgrade – Phase 2',
          budget: '$18,000,000', deadline: '2027-03-01', status: 'Approved',
          location: 'Austin, Texas', contractor: 'GreenWaste Inc',
          createdBy: 'Sarah', lastReviewedBy: 'Robert', lastChangedBy: 'Robert'
        }
      ]);

      // ── 2. Seed Documents + AIResults with example JSON sections ───────────
      const now = new Date().toISOString();

      const seeds = [
        {
          tenderId: 'TND-001',
          docId: 'doc-seed-001',
          filename: 'metro-line-4a-tender.pdf',
          sections: [
            { heading: 'tender_information', sub_headings: [
              { heading: 'tender_title', content: 'Construction of Metro Line 4A – Elevated Corridor' },
              { heading: 'tender_no', content: 'MTL/MMRC/2026/T-01' },
              { heading: 'issuing_authority', content: 'Mumbai Metro Rail Corporation Ltd. (MMRC)' },
              { heading: 'tender_type', content: 'Works – EPC (Engineering, Procurement & Construction)' },
              { heading: 'bid_type', content: 'Two-Envelope System' },
              { heading: 'estimated_cost', content: '₹12,000 Crore (approx.)' },
              { heading: 'funding_agency', content: 'Japan International Cooperation Agency (JICA)' },
              { heading: 'tender_fee', content: '₹50,000 (non-refundable)' },
              { heading: 'contact_details', sub_headings: [
                { heading: 'name', content: 'Rajesh Kumar' },
                { heading: 'designation', content: 'General Manager (Projects)' },
                { heading: 'email', content: 'gm.projects@mmrc.co.in' },
                { heading: 'mobile', content: '+91-22-26591000' }
              ]}
            ]},
            { heading: 'key_dates', sub_headings: [
              { heading: 'release_date', content: '01/06/2026' },
              { heading: 'pre_bid_meeting', content: '15/06/2026 at 11:00 Hours (IST)' },
              { heading: 'bid_submission_deadline', content: '31/12/2026 up to 17:00 Hours (IST)' },
              { heading: 'technical_opening_date', content: '01/01/2027 at 11:00 Hours (IST)' }
            ]},
            { heading: 'scope_of_work', sub_headings: [
              { heading: 'type', content: 'Elevated Metro Viaduct and Stations' },
              { heading: 'location', content: 'Wadala to Kasarvadavali, Mumbai, Maharashtra' },
              { heading: 'components', content: '17.8 km elevated viaduct; 13 stations; depot at Vikhroli; track laying and electrification; signalling and telecommunications systems' }
            ]},
            { heading: 'bid_security_financials', sub_headings: [
              { heading: 'emd', content: '₹120 Crore (1% of estimated project cost) via Bank Guarantee' },
              { heading: 'bid_validity', content: '180 days from the date of bid opening' },
              { heading: 'performance_security', content: '5% of Contract Price, valid through Defects Liability Period' }
            ]},
            { heading: 'contract_conditions', sub_headings: [
              { heading: 'completion_time', content: '48 months from the Effective Date of Contract' },
              { heading: 'defect_liability_period', content: '24 months after completion' },
              { heading: 'liquidated_damages', content: '0.05% of Contract Price per week of delay, subject to maximum 10% of Contract Price' }
            ]}
          ]
        },
        {
          tenderId: 'TND-002',
          docId: 'doc-seed-002',
          filename: 'smart-grids-berlin-tender.pdf',
          sections: [
            { heading: 'tender_information', sub_headings: [
              { heading: 'tender_title', content: 'Smart Grids Power Distribution Upgrade – Zone 4' },
              { heading: 'tender_no', content: 'SGPD/BER/2026/T-03' },
              { heading: 'issuing_authority', content: 'Berliner Stadtwerke GmbH' },
              { heading: 'tender_type', content: 'Supply & Installation' },
              { heading: 'bid_type', content: 'Open Competitive Bidding' },
              { heading: 'estimated_cost', content: '€38,000,000' },
              { heading: 'funding_agency', content: 'European Investment Bank (EIB)' },
              { heading: 'contact_details', sub_headings: [
                { heading: 'name', content: 'Hans Weber' },
                { heading: 'designation', content: 'Head of Procurement' },
                { heading: 'email', content: 'procurement@stadtwerke-berlin.de' }
              ]}
            ]},
            { heading: 'key_dates', sub_headings: [
              { heading: 'release_date', content: '05/04/2026' },
              { heading: 'bid_submission_deadline', content: '15/10/2026 at 14:00 CET' },
              { heading: 'technical_opening_date', content: '16/10/2026 at 10:00 CET' },
              { heading: 'financial_opening_date', content: 'To be announced after technical evaluation' }
            ]},
            { heading: 'scope_of_work', sub_headings: [
              { heading: 'type', content: 'Smart Grid Infrastructure Modernisation' },
              { heading: 'location', content: 'Berlin Zone 4 – Mitte, Prenzlauer Berg, Friedrichshain' },
              { heading: 'components', content: 'Advanced Metering Infrastructure (AMI) for 120,000 households; 42 smart substations; SCADA integration; fibre-optic communication backbone; demand response management system' }
            ]},
            { heading: 'bid_security_financials', sub_headings: [
              { heading: 'emd', content: '€380,000 (1% of estimated contract value)' },
              { heading: 'bid_validity', content: '150 days from submission deadline' },
              { heading: 'performance_security', content: '10% of Contract Price' }
            ]},
            { heading: 'contract_conditions', sub_headings: [
              { heading: 'completion_time', content: '30 months from Effective Date' },
              { heading: 'defect_liability_period', content: '12 months after final acceptance' },
              { heading: 'liquidated_damages', content: '0.1% of undelivered portion per week, capped at 8% of Contract Price' }
            ]}
          ]
        },
        {
          tenderId: 'TND-003',
          docId: 'doc-seed-003',
          filename: 'waste-treatment-austin-tender.pdf',
          sections: [
            { heading: 'tender_information', sub_headings: [
              { heading: 'tender_title', content: 'Waste Treatment Facility Upgrade – Phase 2' },
              { heading: 'tender_no', content: 'WTF/AUS/2026/T-07' },
              { heading: 'issuing_authority', content: 'City of Austin – Public Works Department' },
              { heading: 'tender_type', content: 'Design-Build' },
              { heading: 'bid_type', content: 'Request for Proposal (RFP)' },
              { heading: 'estimated_cost', content: '$18,000,000' },
              { heading: 'funding_agency', content: 'EPA Brownfields Grant + City Capital Budget' },
              { heading: 'contact_details', sub_headings: [
                { heading: 'name', content: 'Maria Santos' },
                { heading: 'designation', content: 'Senior Procurement Officer' },
                { heading: 'email', content: 'procurement@austintexas.gov' },
                { heading: 'mobile', content: '+1-512-974-7890' }
              ]}
            ]},
            { heading: 'key_dates', sub_headings: [
              { heading: 'release_date', content: '10/01/2026' },
              { heading: 'pre_bid_meeting', content: '25/01/2026 at 09:00 CST' },
              { heading: 'bid_submission_deadline', content: '01/03/2027 at 17:00 CST' },
              { heading: 'technical_opening_date', content: '02/03/2027 at 09:00 CST' }
            ]},
            { heading: 'scope_of_work', sub_headings: [
              { heading: 'type', content: 'Wastewater Treatment Plant Upgrade and Expansion' },
              { heading: 'location', content: 'South Austin Treatment Plant, 1017 Talmadge St, Austin TX 78702' },
              { heading: 'components', content: 'Biological nutrient removal upgrade; new secondary clarifiers (×2); UV disinfection system replacement; SCADA modernisation; capacity expansion from 25 MGD to 40 MGD; sludge dewatering centrifuges' }
            ]},
            { heading: 'bid_security_financials', sub_headings: [
              { heading: 'emd', content: '5% of bid amount via cashier\'s check or surety bond' },
              { heading: 'bid_validity', content: '90 days from bid opening date' },
              { heading: 'performance_security', content: '100% Performance Bond + 100% Payment Bond required' }
            ]},
            { heading: 'contract_conditions', sub_headings: [
              { heading: 'completion_time', content: '36 months from Notice to Proceed' },
              { heading: 'defect_liability_period', content: '18 months after substantial completion' },
              { heading: 'liquidated_damages', content: '$2,500 per calendar day of delay' }
            ]}
          ]
        }
      ];

      for (const seed of seeds) {
        await INSERT.into(Documents).entries({
          ID: seed.docId,
          tender_ID: seed.tenderId,
          filename: seed.filename,
          mimeType: 'application/pdf',
          uploadedBy: 'system',
          uploadedAt: now,
        });

        await INSERT.into(AIResults).entries({
          ID: `air-seed-${seed.tenderId.toLowerCase()}`,
          document_ID: seed.docId,
          confidenceScore: 'high',
          summary: seed.sections[0]?.sub_headings?.[0]?.content || seed.tenderId,
          keyTerms: JSON.stringify(seed.sections[0]?.sub_headings?.map(s => s.heading) || []),
          rawResponse: JSON.stringify({ sections: seed.sections }),
          processedAt: now,
        });
      }

      console.log('[TenderService] Seeded initial tender data with AI sections.');
    }
  });

  // ── PATCH Tender: auto-increment version ────────────────────────────────────
  srv.before('UPDATE', Tenders, async (req) => {
    const id = req.data.ID || req.params[0]?.ID || req.params[0];
    if (!id) return;
    const existing = await SELECT.one.from(Tenders).where({ ID: id });
    if (existing) {
      req.data.version = (existing.version || 1) + 1;
    }
  });

  // ── Bound Action: incrementVersion (explicit call) ──────────────────────────
  srv.on('incrementVersion', Tenders, async (req) => {
    const id = req.params[0]?.ID || req.params[0];
    const existing = await SELECT.one.from(Tenders).where({ ID: id });
    if (!existing) return req.error(404, `Tender ${id} not found`);
    const newVersion = (existing.version || 1) + 1;
    await UPDATE(Tenders).set({ version: newVersion }).where({ ID: id });
    return SELECT.one.from(Tenders).where({ ID: id });
  });

  // ── Action: login ────────────────────────────────────────────────────────────
  // Simple credential store — replace with XSUAA in production.
  const USERS = {
    admin   : { password: 'admin123', role: 'admin' },
    reviewer: { password: 'review123', role: 'reviewer' },
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

    // Validate tender exists
    const tender = await SELECT.one.from(Tenders).where({ ID: tenderId });
    if (!tender) return req.error(404, `Tender ${tenderId} not found`);

    const id = cds.utils.uuid();
    const entry = {
      ID: id,
      tender_ID: tenderId,
      fieldName,
      oldVal,
      newVal,
      remark: remark || 'No remarks provided',
      changedBy,
      changedAt: new Date().toISOString()
    };
    await INSERT.into(TenderAudits).entries(entry);
    return SELECT.one.from(TenderAudits).where({ ID: id });
  });

  // ── Action: processFile ──────────────────────────────────────────────────────
  srv.on('processFile', async (req) => {
    const { tenderId, filename, content, mimeType } = req.data;
    const uploadedAt = new Date().toISOString();
    const uploadedBy = req.user?.id || 'unknown';

    // 1. Forward raw bytes to Python AI service
    let pyTenders = null;  // array from Python: [{ confidenceScore, summary, keyTerms, sections }]

    let pyError = null;

    if (axios) {
      try {
        const FormData = require('form-data');
        const form = new FormData();
        const buffer = Buffer.isBuffer(content)
          ? content
          : Buffer.from(content, 'base64');
        form.append('invoice', buffer, { filename, contentType: mimeType || 'application/octet-stream' });

        const pyRes = await axios.post(`${PYTHON_AI_URL}/process_file`, form, {
          headers: form.getHeaders(),
          timeout: 300_000
        });
        pyTenders = pyRes.data?.tenders || null;
      } catch (err) {
        // Surface the real error — connection refused, 5xx from Python, timeout, etc.
        if (err.code === 'ECONNREFUSED') {
          pyError = `Python AI service is not running on ${PYTHON_AI_URL}. Start it with: cd python-ai-service && python app.py`;
        } else if (err.code === 'ETIMEDOUT' || err.code === 'ECONNABORTED') {
          pyError = `Python AI service timed out processing ${filename}. The file may be too large.`;
        } else if (err.response) {
          // Python returned a 4xx/5xx — get the actual error body
          const body = err.response.data;
          pyError = `Python AI error ${err.response.status}: ${typeof body === 'object' ? JSON.stringify(body) : body}`;
        } else {
          pyError = `Python AI error: ${err.message}`;
        }
        console.error('[TenderService]', pyError);
      }
    }

    // 2. Handle no AI response — store document, return descriptive error
    if (!pyTenders) {
      const docId = cds.utils.uuid();
      await INSERT.into(Documents).entries({
        ID: docId, tender_ID: tenderId || null, filename,
        mimeType: mimeType || 'application/octet-stream', content, uploadedBy, uploadedAt
      });
      return JSON.stringify({
        results: [],
        message: pyError || 'Python AI service unavailable. Document stored.'
      });
    }

    // 3. Handle empty tenders array (no tender found in PDF)
    if (pyTenders.length === 0) {
      const docId = cds.utils.uuid();
      await INSERT.into(Documents).entries({
        ID: docId, tender_ID: tenderId || null, filename,
        mimeType: mimeType || 'application/octet-stream', content, uploadedBy, uploadedAt
      });
      return JSON.stringify({ results: [], message: 'No tender information found in the document.' });
    }

    // 4. Helper: extract a sub_heading value from a section
    const getSubField = (sections, sectionHeading, fieldHeading) => {
      const sec = (sections || []).find(s => s.heading === sectionHeading);
      if (!sec) return null;
      const sh = (sec.sub_headings || []).find(h => h.heading === fieldHeading);
      return sh?.content || null;
    };

    // Helper: parse any date string → YYYY-MM-DD (HANA DATE format), or null
    const parseDate = (str) => {
      if (!str) return null;
      const s = String(str);
      // Already YYYY-MM-DD
      let m = s.match(/(\d{4})-(\d{2})-(\d{2})/);
      if (m) return `${m[1]}-${m[2]}-${m[3]}`;
      // DD/MM/YYYY or DD-MM-YYYY (most Indian/European tender formats)
      m = s.match(/(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})/);
      if (m) return `${m[3]}-${m[2].padStart(2,'0')}-${m[1].padStart(2,'0')}`;
      return null;
    };

    // 5. Auto-generate next tender ID
    const getNextTenderId = async () => {
      const rows = await SELECT.from(Tenders).columns('ID');
      const nums = rows
        .map(r => parseInt((r.ID || '').replace('TND-', ''), 10))
        .filter(n => !isNaN(n));
      const next = nums.length > 0 ? Math.max(...nums) + 1 : 1;
      return `TND-${String(next).padStart(3, '0')}`;
    };

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

    // 6. Process each tender returned by AI
    const results = [];

    for (const aiTender of pyTenders) {
      const sections = aiTender.sections || [];

      // Extract key fields
      const rawTenderNo         = getSubField(sections, 'tender_information', 'tender_no') || '';
      const extractedTenderNo   = normalizeTenderNo(rawTenderNo);
      const extractedTitle      = getSubField(sections, 'tender_information', 'tender_title')   || aiTender.summary || 'Untitled Tender';
      const extractedBudget     = getSubField(sections, 'tender_information', 'estimated_cost');
      const extractedDeadline   = parseDate(getSubField(sections, 'key_dates', 'bid_submission_deadline'));
      const extractedLocation   = getSubField(sections, 'scope_of_work',      'location');
      const extractedAuthority  = getSubField(sections, 'tender_information', 'issuing_authority');
      // Try explicit version field first, then extract from raw tender_no (e.g. "VERSION- 2" or "V-2")
      const versionFromTenderNo = (() => {
        const m = rawTenderNo.match(/VERSION\s*-?\s*(\d+)/i) || rawTenderNo.match(/\bV\s*-\s*(\d+)\b/i);
        return m ? parseInt(m[1], 10) : null;
      })();
      const extractedVersion    = parseInt(getSubField(sections, 'tender_information', 'version'), 10) || versionFromTenderNo || 1;

      // Save document (linked later once we know tender ID)
      const docId = cds.utils.uuid();

      // Check for existing tender: first by tenderNo, then by the tenderId passed from UI
      let existingTender = null;
      if (extractedTenderNo) {
        existingTender = await SELECT.one.from(Tenders).where({ tenderNo: extractedTenderNo });
      }
      if (!existingTender && tenderId) {
        existingTender = await SELECT.one.from(Tenders).where({ ID: tenderId });
      }

      let resultTenderId;
      let isNew = false;
      let changedFields = [];
      let pendingPatch = null;

      if (!existingTender) {
        // ── Branch A: genuinely new tender (no match by tenderNo OR passed ID) ─
        isNew = true;
        resultTenderId = await getNextTenderId();

        await INSERT.into(Tenders).entries({
          ID:            resultTenderId,
          tenderNo:      extractedTenderNo || '',
          version:       extractedVersion,
          title:         extractedTitle,
          budget:        extractedBudget  || 'TBD',
          deadline:      extractedDeadline || null,
          status:        'Draft',
          location:      extractedLocation || '',
          contractor:    'Not Selected',
          createdBy:     uploadedBy,
          lastReviewedBy: '-',
          lastChangedBy:  uploadedBy,
        });

      } else {
        // ── Branch B: duplicate found — always ask user to confirm ────────────
        resultTenderId = existingTender.ID;

        // Show all extracted fields (existing vs new) so user can decide
        const allFields = [
          { field: 'Tender No', dbKey: 'tenderNo', newVal: extractedTenderNo },
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
        // Do NOT update DB — return requiresConfirmation so React asks the user first
      }

      // Save document linked to this tender
      await INSERT.into(Documents).entries({
        ID: docId, tender_ID: resultTenderId, filename,
        mimeType: mimeType || 'application/octet-stream', content, uploadedBy, uploadedAt
      });

      // Generate PDF synopsis via Python and save alongside the JSON
      let pdfBuffer = null;
      if (axios) {
        try {
          const pdfRes = await axios.post(`${PYTHON_AI_URL}/generate_pdf`, {
            sections,
            title: aiTender.summary || extractedTitle,
          }, { timeout: 30_000, responseType: 'arraybuffer' });
          pdfBuffer = Buffer.from(pdfRes.data);
        } catch (pdfErr) {
          console.warn('[TenderService] PDF generation skipped:', pdfErr.message);
        }
      }

      // Save AIResult linked to document (pdfContent saved separately — column may not be deployed yet)
      const aiResultId = cds.utils.uuid();
      await INSERT.into(AIResults).entries({
        ID:              aiResultId,
        document_ID:     docId,
        confidenceScore: String(aiTender.confidenceScore || 'high'),
        summary:         aiTender.summary || '',
        keyTerms:        JSON.stringify(aiTender.keyTerms || []),
        rawResponse:     JSON.stringify({ sections }),
        processedAt:     new Date().toISOString(),
      });
      if (pdfBuffer) {
        try {
          await UPDATE(AIResults).set({ pdfContent: pdfBuffer }).where({ ID: aiResultId });
        } catch (pdfSaveErr) {
          console.warn('[TenderService] Could not cache PDF in HANA (pdfContent column may not be deployed yet):', pdfSaveErr.message);
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
          tenderNo:           extractedTenderNo || '',
          title:              extractedTitle || '',
          budget:             extractedBudget || '',
          deadline:           extractedDeadline || '',
          location:           extractedLocation || '',
        }
      });
    }

    // 7. Return results array to React
    return JSON.stringify({ results });
  });

  // ── Action: applyTenderUpdate ────────────────────────────────────────────────
  // Called by React after the user confirms a duplicate-update prompt.
  srv.on('applyTenderUpdate', async (req) => {
    const { tenderId, patch, changedFields } = req.data;
    const patchObj        = JSON.parse(patch);
    const changedFieldsArr = JSON.parse(changedFields);

    const tender = await SELECT.one.from(Tenders).where({ ID: tenderId });
    if (!tender) return req.error(404, `Tender ${tenderId} not found`);

    await UPDATE(Tenders).set(patchObj).where({ ID: tenderId });

    for (const { field, oldVal, newVal } of changedFieldsArr) {
      await INSERT.into(TenderAudits).entries({
        ID:        cds.utils.uuid(),
        tender_ID: tenderId,
        fieldName: field,
        oldVal,
        newVal,
        remark:    'Updated from PDF upload (user confirmed)',
        changedBy: patchObj.lastChangedBy || 'unknown',
        changedAt: new Date().toISOString(),
      });
    }

    return JSON.stringify({ success: true, tenderId });
  });

  // ── Action: updateAIResult ───────────────────────────────────────────────────
  srv.on('updateAIResult', async (req) => {
    const { id, rawResponse } = req.data;
    const existing = await SELECT.one.from(AIResults).where({ ID: id });
    if (!existing) return req.error(404, `AIResult ${id} not found`);
    await UPDATE(AIResults).set({ rawResponse }).where({ ID: id });
    return JSON.stringify({ success: true });
  });

  // ── Action: chat ──────────────────────────────────────────────────────────────
  srv.on('chat', async (req) => {
    const { tenderId, message, sender } = req.data;
    const timestamp = new Date().toISOString();
    const reqUser  = req.user?.id || 'user';

    // 1. Persist user message
    await INSERT.into(ChatHistories).entries({
      ID: cds.utils.uuid(),
      tender_ID: tenderId || null,
      sender: sender || 'user',
      message,
      timestamp
    });

    // 2. Call Python /response endpoint
    let botReply = '[AI service unavailable] Your message was received.';

    if (axios) {
      try {
        const pyRes = await axios.post(`${PYTHON_AI_URL}/response`, {
          message,
          tenderId,
          user: reqUser
        }, { timeout: 20_000 });

        botReply = pyRes.data?.reply || pyRes.data?.response || JSON.stringify(pyRes.data);
      } catch (err) {
        console.error('[TenderService] Python chat error:', err.message);
        botReply = `[AI Error] ${err.message}. Your message was received.`;
      }
    }

    // 3. Persist bot reply
    await INSERT.into(ChatHistories).entries({
      ID: cds.utils.uuid(),
      tender_ID: tenderId || null,
      sender: 'bot',
      message: botReply,
      timestamp: new Date().toISOString()
    });

    return botReply;
  });

  // ── Action: generatePDF ─────────────────────────────────────────────────────
  // Returns the stored PDF from HANA as a base64 string.
  // If the PDF was never generated (e.g. seeded data), regenerates it on the fly
  // and persists it for next time.
  srv.on('generatePDF', async (req) => {
    const { tenderId } = req.data;
    if (!tenderId) return req.error(400, 'tenderId is required');

    // 1. Find the most recent AIResult that has sections for this tender
    const docs = await SELECT.from(Documents)
      .where({ tender_ID: tenderId })
      .orderBy('uploadedAt desc');

    let aiResult = null;
    for (const doc of docs) {
      const result = await SELECT.one.from(AIResults).where({ document_ID: doc.ID });
      if (result?.rawResponse) {
        aiResult = result;
        break;
      }
    }

    if (!aiResult) {
      return req.error(404, 'No AI-processed data found for this tender. Please upload a PDF first.');
    }

    // 2. Generate PDF fresh every time (always use latest template)
    if (!axios) return req.error(503, 'axios not installed');

    let sections = [];
    try {
      const parsed = JSON.parse(aiResult.rawResponse);
      sections = parsed.sections || [];
    } catch { return req.error(500, 'Failed to parse stored AI data'); }

    let pdfBuffer;
    try {
      const pyRes = await axios.post(`${PYTHON_AI_URL}/generate_pdf`, {
        sections,
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

    // Persist so next download is instant (best-effort — skip if column not deployed yet)
    try {
      await UPDATE(AIResults).set({ pdfContent: pdfBuffer }).where({ ID: aiResult.ID });
    } catch (saveErr) {
      console.warn('[TenderService] Could not cache PDF in HANA (pdfContent column may not be deployed yet):', saveErr.message);
    }

    return pdfBuffer.toString('base64');
  });

});

