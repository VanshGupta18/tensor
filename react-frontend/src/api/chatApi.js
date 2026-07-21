/**
 * api/chatApi.js
 *
 * Chat and file-processing API calls forwarded through CAP → Python AI.
 */

import { callAction } from './client.js';

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
 * Upload a PDF for AI processing (field name must be "invoice" for multer).
 */
export async function uploadFileForProcessing(file, tenderId = null, onProgress = null) {
  const formData = new FormData();
  formData.append('invoice', file);
  if (tenderId) formData.append('tenderId', tenderId);

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

  // Backend returns 202 Accepted with a jobId for async processing
  const { jobId } = await response.json();
  return pollJobStatus(jobId, onProgress);
}

/**
 * Polls the backend for job completion status.
 * Invokes onProgress(job) on every poll so the UI can update in real time.
 */
async function pollJobStatus(jobId, onProgress = null) {
  const POLL_MS = 800;
  while (true) {
    const res = await fetch(`/upload/status/${jobId}`);
    if (!res.ok) throw new Error(`Status check failed: HTTP ${res.status}`);

    const job = await res.json();
    if (onProgress) onProgress(job);

    if (job.status === 'completed') {
      const rawString = job.result?.value ?? job.result;
      try {
        return typeof rawString === 'string' ? JSON.parse(rawString) : rawString;
      } catch {
        return { results: [], message: String(rawString) };
      }
    }
    if (job.status === 'failed') {
      throw new Error(job.error || 'Upload processing failed asynchronously');
    }

    await new Promise(resolve => setTimeout(resolve, POLL_MS));
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

