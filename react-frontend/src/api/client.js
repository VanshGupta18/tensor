/**
 * api/client.js
 *
 * Central fetch wrapper for CAP OData V4 + action calls.
 * Base URL is proxied through Vite dev server: /api → http://localhost:4004
 * In production, set VITE_API_BASE_URL to the deployed CAP URL.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api') + '/odata/v4/tender';

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    let errMsg = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      errMsg = body?.error?.message || body?.message || errMsg;
    } catch { /* ignore JSON parse errors */ }
    throw new ApiError(errMsg, response.status);
  }

  // 204 No Content
  if (response.status === 204) return null;
  return response.json();
}

// ── OData V4 helpers ──────────────────────────────────────────────────────────

export const api = {
  get: (path, opts)  => request(path, { method: 'GET',   ...opts }),
  post: (path, body) => request(path, { method: 'POST',  body: JSON.stringify(body) }),
  patch: (path, body)=> request(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: (path)     => request(path, { method: 'DELETE' }),
};

/**
 * Call a CAP unbound action via POST.
 * Actions live under:  /odata/v4/tender/<ActionName>
 */
export async function callAction(actionName, params = {}) {
  return request(`/${actionName}`, {
    method: 'POST',
    body: JSON.stringify(params),
  });
}

export default api;
