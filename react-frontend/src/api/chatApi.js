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

export async function streamChatMessage(message, tenderId = null, onChunk, history = []) {
  const res = await fetch('/api/stream-chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, tenderId, history }),
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
/**
 * Upload a PDF for AI processing.
 *
 * Request path:  Browser → Vite proxy (/upload) → CAP (:4004/upload)
 *                       → Python AI (:8000/process_file)
 *
 * The field name MUST be "invoice" — multer in server.js is keyed to that name.
 * tenderId is optional; when provided, CAP uses it as a duplicate-detection hint.
 *
 * Throws an Error whose message is the human-readable failure reason.
 * The caller (ChatbotPanel) shows err.message directly — do NOT wrap it in
 * another "Upload failed:" prefix here (that causes the double-prefix bug).
 */
export async function uploadFileForProcessing(file, tenderId = null) {
  const formData = new FormData();
  formData.append('invoice', file);           // field name must match multer config
  if (tenderId) formData.append('tenderId', tenderId);

  // No Content-Type header — the browser sets it automatically with the
  // correct multipart boundary when body is FormData.
  const response = await fetch('/upload', { method: 'POST', body: formData });

  if (!response.ok) {
    // Try to extract the structured error the server sends back as JSON.
    // Fallback to the HTTP status line if the body is an HTML error page
    // (e.g. Express default 500, or Vite proxy HTML 502).
    let errMsg = `HTTP ${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      // Server returns { error: string } or { error: { message: string } }
      errMsg = body?.error?.message ?? body?.error ?? body?.message ?? errMsg;
    } catch {
      // Non-JSON body (HTML page from proxy/Express default error handler)
      if (response.status === 502) {
        errMsg = 'Could not reach the backend (502). Is the CAP server running on port 4004?';
      }
    }
    throw new Error(errMsg);
  }

  // CAP wraps action returns in { value: <string> }; unwrap and parse
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

