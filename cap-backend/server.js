'use strict';
/**
 * server.js — CAP custom server bootstrap
 *
 * Adds a dedicated multipart upload route (/upload) that accepts raw binary
 * from the browser — no base64 inflation — to avoid SAP BAS proxy body limits.
 *
 * Flow:  Browser → /upload (multipart, raw binary)
 *             → buffer.toString('base64')   [in-process, no network]
 *             → TenderService.processFile action  [local dispatch]
 */

const cds    = require('@sap/cds');
const multer = require('multer');
const rateLimit = require('express-rate-limit');

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
  // Apply chat rate limiter before CAP routes are registered
  app.use('/odata/v4/tender/chat', chatLimiter);

  app.post('/upload', uploadLimiter, upload.single('invoice'), async (req, res) => {
    if (!req.file) {
      return res.status(400).json({ error: 'No file uploaded. Field name must be "invoice".' });
    }

    try {
      const file     = req.file;
      const tenderId = req.body.tenderId || null;

      // Convert raw binary to base64 in-process (local, no proxy hop)
      const base64Content = file.buffer.toString('base64');

      // Dispatch to the CDS service action — local function call, not HTTP
      const srv    = await cds.connect.to('TenderService');
      
      // Since /upload is an Express route outside of OData, it lacks CAP's req.user
      // We must provide a privileged user context to bypass @requires: 'authenticated-user'
      const contextUser = new cds.User.Privileged('system');
      const result = await srv.tx({ user: contextUser }).send('processFile', {
        tenderId,
        filename: file.originalname,
        content:  base64Content,
        mimeType: file.mimetype || 'application/octet-stream',
      });

      res.json({ value: result });
    } catch (err) {
      console.error('[/upload]', err.stack);
      res.status(500).json({ error: err.message || 'Upload failed', stack: err.stack });
    }
  });
});

module.exports = cds.server;
