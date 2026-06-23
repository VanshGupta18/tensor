/**
 * api/chatApi.js
 *
 * Chat and file-processing API calls forwarded through CAP → Python AI.
 */

import { callAction } from './client.js';

/**
 * Send a text message to the AI chatbot.
 *
 * @param {string} message   - The user's question.
 * @param {string} tenderId  - Optional: context tender ID (null if global).
 * @param {string} sender    - 'user' | 'bot'
 * @returns {Promise<string>} - The bot's reply text.
 */
export async function sendChatMessage(message, tenderId = null, sender = 'user') {
  const result = await callAction('chat', { message, tenderId, sender });
  // CAP wraps scalar action returns in { value: <string> }
  return result?.value ?? result;
}

/**
 * Upload a file for AI processing.
 * Sends raw binary as multipart/form-data to /upload — no base64 inflation,
 * avoiding SAP BAS proxy body-size limits that cut large PDFs mid-transfer.
 *
 * @param {File}   file      - Browser File object.
 * @param {string} tenderId  - Optional: context tender ID.
 * @returns {Promise<object>} - Parsed AI result JSON.
 */
export async function uploadFileForProcessing(file, tenderId = null) {
  const formData = new FormData();
  formData.append('invoice', file);
  if (tenderId) formData.append('tenderId', tenderId);

  const response = await fetch('/upload', { method: 'POST', body: formData });

  if (!response.ok) {
    const err = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
    throw new Error(err.error || `Upload failed: HTTP ${response.status}`);
  }

  const json      = await response.json();
  const rawString = json?.value ?? json;
  try {
    return typeof rawString === 'string' ? JSON.parse(rawString) : rawString;
  } catch {
    return { results: [], message: String(rawString) };
  }
}

/**
 * Apply a confirmed duplicate-tender update.
 * Called after the user clicks "Yes, update" in the chatbot confirmation card.
 */
export async function applyTenderUpdate(tenderId, patch, changedFields) {
  const result = await callAction('applyTenderUpdate', {
    tenderId,
    patch:        JSON.stringify(patch),
    changedFields: JSON.stringify(changedFields),
  });
  const rawString = result?.value ?? result;
  try { return JSON.parse(rawString); } catch { return rawString; }
}

