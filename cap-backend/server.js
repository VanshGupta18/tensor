'use strict';
/**
 * server.js — CAP custom server bootstrap
 *
 * Custom express routes must be registered here (not in service.js) because
 * cds.on('bootstrap') fires before service implementation files are loaded.
 * Routes registered in service.js bootstrap handlers are never called.
 *
 * Routes registered here:
 *   POST /upload           — multipart PDF upload forwarded to TenderService.processFile
 *   POST /api/stream-chat  — SSE streaming chat, proxied from Python AI service
 *   POST /stream-chat      — same handler, used by Vite dev proxy (strips /api prefix)
 *   GET  /api/analytics/live — live (in-memory, unpersisted) processing analytics
 *   GET  /analytics/live     — same handler, used by Vite dev proxy (strips /api prefix)
 */

const cds    = require('@sap/cds');
const multer = require('multer');
const rateLimit = require('express-rate-limit');
const jwt       = require('jsonwebtoken');
const { json: parseJson } = require('express');
const { streamChatHandler } = require('./srv/controllers/chatController');
const { getLiveAnalyticsHandler } = require('./srv/controllers/analyticsController');

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
  storage: multer.diskStorage({
    destination: (req, file, cb) => cb(null, '.tmp/uploads/'),
    filename: (req, file, cb) => cb(null, Date.now() + '-' + file.originalname)
  }),
  limits:  { fileSize: 50 * 1024 * 1024 },   // 50 MB
});

// In-memory job tracker for asynchronous AI processing
const uploadJobs = new Map();

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
    upload.single('invoice')(req, res, async (multerErr) => {
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

      const file = req.file;
      const tenderId = req.body.tenderId || null;
      const jobId = cds.utils.uuid();

      // Track job status
      uploadJobs.set(jobId, { status: 'processing', result: null, error: null });

      // Return 202 Accepted immediately so frontend isn't blocked
      res.status(202).json({ jobId, status: 'processing', message: 'File is being processed asynchronously.' });

      // Process in the background
      (async () => {
        try {
          const srv = await cds.connect.to('TenderService');
          const contextUser = new cds.User.Privileged('system');
          
          // Instead of base64 content, we pass the local filepath
          const result = await srv.tx({ user: contextUser }).send('processFile', {
            tenderId,
            filename: file.originalname,
            filepath: file.path,
            mimeType: file.mimetype || 'application/octet-stream',
          });

          uploadJobs.set(jobId, { status: 'completed', result });
        } catch (err) {
          console.error('[/upload] processFile error:', err.stack);
          uploadJobs.set(jobId, { status: 'failed', error: err.message || 'Upload processing failed' });
        }
      })();
    });
  });

  // ── GET /upload/status/:jobId ────────────────────────────────────────────────
  // Polling endpoint for the React frontend to check on background job status
  app.get('/upload/status/:jobId', (req, res) => {
    const job = uploadJobs.get(req.params.jobId);
    if (!job) return res.status(404).json({ error: 'Job not found' });
    
    // If completed or failed, we can optionally clean up the map to prevent memory leaks
    if (job.status === 'completed' || job.status === 'failed') {
      setTimeout(() => uploadJobs.delete(req.params.jobId), 60000); // clear after 1 minute
    }
    
    res.json(job);
  });

  // ── Streaming chat (/api/stream-chat + /stream-chat) ──────────────────────
  // Proxies Python SSE chunks to the browser; persists conversation in HANA.
  // Registered under both paths: Vite dev proxy strips /api (/stream-chat),
  // production (React built into CAP app/) uses /api/stream-chat directly.


  app.use(['/api/stream-chat', '/stream-chat'], chatLimiter);
  app.post('/api/stream-chat', parseJson(), streamChatHandler);
  app.post('/stream-chat', parseJson(), streamChatHandler);

  // ── Live analytics (/api/analytics/live + /analytics/live) ────────────────
  // Polled on an interval by the Analytics screen. No database read/write —
  // straight proxy to the Python service's in-memory processing sessions.
  app.get('/api/analytics/live', getLiveAnalyticsHandler);
  app.get('/analytics/live', getLiveAnalyticsHandler);
});

module.exports = cds.server;

// Trigger restart
