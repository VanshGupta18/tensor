'use strict';

const cds = require('@sap/cds');
const axios = require('axios');
const { PYTHON_AI_URL } = require('../services/aiService');
const { getLatestContentHash } = require('../utils/documentLookup');

/**
 * Handles streaming chat responses by proxying to the Python AI service.
 * Session-only — no ChatHistories persistence. The frontend never reads chat history
 * back from the server (ChatbotPanel only shows the current in-memory session), so
 * durably storing every message was pure write-only overhead.
 */
const streamChatHandler = async (req, res) => {
  const { message, tenderId, history } = req.body || {};
  if (!message) return res.status(400).json({ error: 'message is required' });

  if (cds.env.requires?.auth?.kind === 'xsuaa' && !req.headers.authorization) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders();

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
  const contentHash = await getLatestContentHash(tenderId);

  try {
    const pyRes = await axios.post(
      `${PYTHON_AI_URL}/stream-response`,
      { message, tenderId: pythonTenderRef, history: Array.isArray(history) ? history : [], contentHash },
      { responseType: 'stream', timeout: 62_000 }
    );

    pyRes.data.on('data', (chunk) => {
      res.write(chunk.toString());
    });

    pyRes.data.on('end', () => {
      res.end();
    });

    pyRes.data.on('error', (err) => {
      console.error('[stream-chat] stream error:', err.message);
      res.write(`data: ${JSON.stringify({ error: err.message })}\\n\\ndata: [DONE]\\n\\n`);
      res.end();
    });

  } catch (err) {
    console.error('[stream-chat] Python call failed:', err.message);
    res.write(`data: ${JSON.stringify({ error: err.message })}\\n\\ndata: [DONE]\\n\\n`);
    res.end();
  }
};

module.exports = {
  streamChatHandler
};
