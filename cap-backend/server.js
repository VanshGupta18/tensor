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

const upload = multer({
  storage: multer.memoryStorage(),
  limits:  { fileSize: 50 * 1024 * 1024 },   // 50 MB
});

cds.on('bootstrap', (app) => {
  app.post('/upload', upload.single('invoice'), async (req, res) => {
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
      const result = await srv.send('processFile', {
        tenderId,
        filename: file.originalname,
        content:  base64Content,
        mimeType: file.mimetype || 'application/octet-stream',
      });

      res.json({ value: result });
    } catch (err) {
      console.error('[/upload]', err.message);
      res.status(500).json({ error: err.message || 'Upload failed' });
    }
  });
});

module.exports = cds.server;
