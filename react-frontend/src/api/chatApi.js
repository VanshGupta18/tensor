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
 * Converts the File to a base64-encoded string before sending.
 *
 * @param {File}   file      - Browser File object.
 * @param {string} tenderId  - Optional: context tender ID.
 * @returns {Promise<object>} - Parsed AI result JSON.
 */
export async function uploadFileForProcessing(file, tenderId = null) {
  const base64Content = await fileToBase64(file);

  const result = await callAction('processFile', {
    tenderId,
    filename: file.name,
    mimeType: file.type || 'application/octet-stream',
    content:  base64Content,
  });

  // CAP wraps scalar string return in { value: "<json string>" }
  const rawString = result?.value ?? result;
  try {
    return JSON.parse(rawString);
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

// ── Utility ──────────────────────────────────────────────────────────────────

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result.split(',')[1]); // strip data:...;base64, prefix
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}
