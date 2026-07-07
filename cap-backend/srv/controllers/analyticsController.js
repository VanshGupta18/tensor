'use strict';

let axios;
try {
  axios = require('axios');
} catch {
  console.warn('[analyticsController] axios not installed – live analytics will fail.');
}

const { PYTHON_AI_URL } = require('../services/aiService');

/**
 * Proxies the Python AI service's in-memory processing sessions straight through —
 * nothing here is read from or written to the database. The Analytics screen polls
 * this on an interval to show token/time counters live while a document is being
 * processed, with no persisted history.
 */
const getLiveAnalyticsHandler = async (req, res) => {
  try {
    if (!axios) throw new Error('axios is not installed on the server.');
    const pyRes = await axios.get(`${PYTHON_AI_URL}/analytics/live`, { timeout: 10_000 });
    res.json(pyRes.data);
  } catch (err) {
    console.error('[analytics/live] Python call failed:', err.message);
    res.status(502).json({ error: `Python AI service unavailable: ${err.message}`, sessions: [] });
  }
};

module.exports = {
  getLiveAnalyticsHandler
};
