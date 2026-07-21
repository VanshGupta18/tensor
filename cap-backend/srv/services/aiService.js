'use strict';
const fs = require('fs');

const axios = require('axios');
const FormData = require('form-data');
const PYTHON_AI_URL = process.env.PYTHON_AI_URL || 'http://localhost:8002';

/**
 * Sends a PDF to the Python AI Service for parsing.
 * @param {string} filepath 
 * @param {string} filename 
 * @param {string} mimeType 
 * @returns {Promise<{ pyTenders: Array|null, pyError: string|null }>}
 */
async function processFileWithAI(filepath, filename, mimeType) {
  let pyTenders = null;
  let pyError = null;

  try {
    const form = new FormData();
    form.append('invoice', fs.createReadStream(filepath), { filename, contentType: mimeType || 'application/octet-stream' });

    const pyRes = await axios.post(`${PYTHON_AI_URL}/process_file`, form, {
      headers: form.getHeaders(),
      timeout: 1_800_000 // 632-page tender exceeded old 600s cap
    });
    pyTenders = pyRes.data?.tenders || null;
  } catch (err) {
    if (err.code === 'ECONNREFUSED') {
      pyError = `Python AI service is not running on ${PYTHON_AI_URL}. Start it with: cd python-ai-service && python app.py`;
    } else if (err.code === 'ETIMEDOUT' || err.code === 'ECONNABORTED') {
      pyError = `Python AI service timed out processing ${filename}. The file may be too large.`;
    } else if (err.response) {
      const body = err.response.data;
      pyError = `Python AI error ${err.response.status}: ${typeof body === 'object' ? JSON.stringify(body) : body}`;
    } else {
      pyError = `Python AI error: ${err.message}`;
    }
    console.error('[aiService]', pyError);
  }

  return { pyTenders, pyError };
}

/**
 * Purge all Python-side artifacts for a content hash (cache, PDF, vectors).
 */
async function purgeDocumentFromAI(contentHash) {
  const res = await axios.post(
    `${PYTHON_AI_URL}/purge_document`,
    { contentHash },
    { timeout: 120_000 },
  );
  return res.data;
}

module.exports = {
  processFileWithAI,
  purgeDocumentFromAI,
  PYTHON_AI_URL,
};
