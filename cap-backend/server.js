'use strict';
/**
 * server.js — CAP custom server bootstrap
 *
 * Custom express routes must be registered here (not in service.js) because
 * cds.on('bootstrap') fires before service implementation files are loaded.
 * Routes registered in service.js bootstrap handlers are never called.
 *
 * Routes registered here:
 *   POST /upload          — multipart PDF upload forwarded to TenderService.processFile
 *   POST /api/stream-chat — SSE streaming chat, proxied from Python AI service
 *   POST /stream-chat     — same handler, used by Vite dev proxy (strips /api prefix)
 */

const cds    = require('@sap/cds');
const multer = require('multer');
const rateLimit = require('express-rate-limit');
const jwt       = require('jsonwebtoken');

let axios;
try { axios = require('axios'); } catch { /* axios unavailable — stream-chat will fail */ }

const { json: parseJson } = require('express');

const PYTHON_AI_URL = process.env.PYTHON_AI_URL || 'http://localhost:8000';

const JWT_SECRET = process.env.JWT_SECRET || 'super-secret-key-for-dev';

// 10 uploads per user per 15 minutes — prevents AI cost abuse and HANA saturation
const uploadLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 10,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  keyGenerator: (req) => req.ip,
  message: { error: 'Too many uploads. Try again in 15 minutes.' },
});

// 60 chat messages per user per minute — keeps Bedrock cost predictable
const chatLimiter = rateLimit({
  windowMs: 60 * 1000,
  limit: 60,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  keyGenerator: (req) => req.ip,
  message: { error: 'Too many chat requests. Slow down.' },
});

const upload = multer({
  storage: multer.memoryStorage(),
  limits:  { fileSize: 50 * 1024 * 1024 },   // 50 MB
});

// Extend server socket timeout so long AI-processing uploads don't get dropped
cds.on('listening', ({ server }) => {
  server.timeout         = 600000;  // 10 min — max time a socket can be idle
  server.keepAliveTimeout = 600000;
  server.headersTimeout  = 610000;  // must be > keepAliveTimeout
});

cds.on('bootstrap', (app) => {
  // ── JWT Authentication Middleware ──────────────────────────────────────────
  app.use((req, res, next) => {
    const authHeader = req.headers.authorization;
    if (authHeader && authHeader.startsWith('Bearer ')) {
      const token = authHeader.split(' ')[1];
      try {
        const decoded = jwt.verify(token, JWT_SECRET);
        req.user = new cds.User({ id: decoded.username, roles: [decoded.role, 'authenticated-user'] });
      } catch (err) {
        // invalid or expired token
      }
    }
    next();
  });

  // Apply chat rate limiter before CAP routes are registered
  app.use('/odata/v4/tender/chat', chatLimiter);

  // ── POST /upload ─────────────────────────────────────────────────────────────
  // Receives a multipart PDF from the React frontend, base64-encodes it in-process,
  // and dispatches to the processFile CDS action which forwards to Python AI.
  //
  // WHY multer inline (not as middleware arg):
  //   When multer is passed as `upload.single()` in the middleware array, its errors
  //   (e.g. file-too-large MulterError) call next(err), which hits Express's default
  //   HTML error handler.  The Vite proxy sees a non-JSON body and may emit a 502.
  //   Running multer inside the handler and catching its callback error lets us return
  //   a clean JSON response for every failure path.
  app.post('/upload', uploadLimiter, (req, res) => {
    // Run multer inside the route so we can catch MulterError and return JSON
    upload.single('invoice')(req, res, async (multerErr) => {
      // ── Multer-level errors (file too large, wrong field name, etc.) ───────
      if (multerErr) {
        const isFileSizeError = multerErr.code === 'LIMIT_FILE_SIZE';
        const status  = isFileSizeError ? 413 : 400;
        const message = isFileSizeError
          ? 'File too large. Maximum 50 MB allowed.'
          : `Upload error: ${multerErr.message}`;
        console.error('[/upload] multer error:', multerErr.message);
        return res.status(status).json({ error: message });
      }

      if (!req.file) {
        return res.status(400).json({ error: 'No file attached. Send the PDF as form-data field "invoice".' });
      }

      try {
        const file     = req.file;
        const tenderId = req.body.tenderId || null;

        // Convert binary buffer to base64 in-process — avoids a second HTTP hop and
        // stays well within the 50 MB multer limit (base64 expands ~33%).
        const base64Content = file.buffer.toString('base64');

        // Dispatch to the CDS TenderService action — this is a local function call,
        // not an HTTP request.  CAP routes it to the srv.on('processFile') handler
        // in service.js, which then calls the Python AI service.
        const srv = await cds.connect.to('TenderService');

        // /upload is an Express route outside of CAP's OData stack, so it has no
        // CAP req.user.  A Privileged context lets processFile bypass auth guards.
        const contextUser = new cds.User.Privileged('system');
        const result = await srv.tx({ user: contextUser }).send('processFile', {
          tenderId,
          filename: file.originalname,
          content:  base64Content,
          mimeType: file.mimetype || 'application/octet-stream',
        });

        res.json({ value: result });
      } catch (err) {
        // Log the full stack for server-side debugging; send a clean message to the client.
        // Avoid leaking stack traces to the browser in production.
        console.error('[/upload] processFile error:', err.stack);
        res.status(500).json({
          error: err.message || 'Upload processing failed',
          // Include stack only in development so the frontend can surface it
          ...(process.env.NODE_ENV !== 'production' && { stack: err.stack }),
        });
      }
    });
  });

  // ── Streaming chat (/api/stream-chat + /stream-chat) ──────────────────────
  // Proxies Python SSE chunks to the browser; persists conversation in HANA.
  // Registered under both paths: Vite dev proxy strips /api (/stream-chat),
  // production (React built into CAP app/) uses /api/stream-chat directly.
  const streamChatHandler = async (req, res) => {
    const { message, tenderId, history } = req.body || {};
    if (!message) return res.status(400).json({ error: 'message is required' });

    if (cds.env.requires?.auth?.kind === 'xsuaa' && !req.headers.authorization) {
      return res.status(401).json({ error: 'Unauthorized' });
    }

    cds.db?.run(
      INSERT.into('TenderService.ChatHistories').entries({
        ID: cds.utils.uuid(),
        tender_ID: tenderId || null,
        sender: 'user',
        message,
        timestamp: new Date().toISOString(),
      })
    ).catch(e => console.error('[stream-chat] user insert failed:', e.message));

    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');
    res.flushHeaders();

    let fullReply = '';
    let pythonTenderRef = tenderId;

    if (tenderId && cds.db) {
      try {
        const t = await cds.db.read('TenderService.Tenders').columns('tenderNo').where({ ID: tenderId });
        if (t && t.length > 0 && t[0].tenderNo) {
          pythonTenderRef = t[0].tenderNo;
        }
      } catch (e) {
        console.error('[stream-chat] failed to fetch tenderNo:', e.message);
      }
    }

    try {
      const pyRes = await axios.post(
        `${PYTHON_AI_URL}/stream-response`,
        { message, tenderId: pythonTenderRef, history: Array.isArray(history) ? history : [] },
        { responseType: 'stream', timeout: 62_000 }
      );

      pyRes.data.on('data', (chunk) => {
        const raw = chunk.toString();
        res.write(raw);
        for (const line of raw.split('\n')) {
          if (line.startsWith('data: ') && line !== 'data: [DONE]') {
            try { const p = JSON.parse(line.slice(6)); if (p.text) fullReply += p.text; } catch {}
          }
        }
      });

      pyRes.data.on('end', async () => {
        res.end();
        if (fullReply) {
          cds.db?.run(
            INSERT.into('TenderService.ChatHistories').entries({
              ID: cds.utils.uuid(),
              tender_ID: tenderId || null,
              sender: 'bot',
              message: fullReply,
              timestamp: new Date().toISOString(),
            })
          ).catch(e => console.error('[stream-chat] bot insert failed:', e.message));
        }
      });

      pyRes.data.on('error', (err) => {
        console.error('[stream-chat] stream error:', err.message);
        res.write(`data: ${JSON.stringify({ error: err.message })}\n\ndata: [DONE]\n\n`);
        res.end();
      });

    } catch (err) {
      console.error('[stream-chat] Python call failed:', err.message);
      res.write(`data: ${JSON.stringify({ error: err.message })}\n\ndata: [DONE]\n\n`);
      res.end();
    }
  };

  app.use(['/api/stream-chat', '/stream-chat'], chatLimiter);
  app.post('/api/stream-chat', parseJson(), streamChatHandler);
  app.post('/stream-chat', parseJson(), streamChatHandler);
});

module.exports = cds.server;

// Trigger restart
