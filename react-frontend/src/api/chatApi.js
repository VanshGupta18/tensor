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
 * Stream a chat message from the AI — calls /api/stream-chat and invokes
 * onChunk(text) for each arriving token. Returns the full reply when done.
 *
 * @param {string}   message   - The user's question.
 * @param {string}   tenderId  - Optional tender context.
 * @param {Function} onChunk   - Called with each text chunk as it arrives.
 * @returns {Promise<string>}  - Full reply text.
 */
const STREAM_TIMEOUT_MS = 90_000;

export async function streamChatMessage(message, tenderId = null, onChunk) {
  const res = await fetch('/api/stream-chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, tenderId }),
  });

  if (!res.ok) throw new Error(`HTTP ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let fullText = '';

  const readWithTimeout = () => {
    const timeout = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('Chat response timed out — no data received for 90s. Please try again.')), STREAM_TIMEOUT_MS)
    );
    return Promise.race([reader.read(), timeout]);
  };

  try {
    while (true) {
      const { done, value } = await readWithTimeout();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete last line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6);
        if (payload === '[DONE]') return fullText;
        try {
          const parsed = JSON.parse(payload);
          if (parsed.error) throw new Error(parsed.error);
          if (parsed.text) {
            fullText += parsed.text;
            onChunk(parsed.text);
          }
        } catch (e) {
          if (e.message !== payload) throw e; // only rethrow real errors
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
  return fullText;
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
    let errMsg = `Upload failed: HTTP ${response.status} ${response.statusText}`;
    try {
      const err = await response.json();
      errMsg = err?.error?.message || err?.error || err?.message || errMsg;
    } catch { /* server returned non-JSON (HTML error page) — use status text */ }
    throw new Error(errMsg);
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

