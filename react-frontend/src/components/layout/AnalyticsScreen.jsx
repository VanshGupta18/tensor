import React from 'react';
import { useQuery } from '@tanstack/react-query';

// Live only — nothing here is read from or written to the database. This polls
// the Python AI service's in-memory processing sessions (via the CAP proxy route
// registered in server.js) so the numbers reflect whatever is happening right now,
// not a persisted history. Sessions are lost on service restart, by design.
const POLL_INTERVAL_MS = 2000;

const STATUS_STYLES = {
  processing: { background: 'var(--warning-bg, #fef3c7)', color: 'var(--warning, #92400e)' },
  done:       { background: 'var(--success-bg, #d1fae5)', color: 'var(--success, #065f46)' },
  error:      { background: 'var(--danger-bg, #fee2e2)',  color: 'var(--danger, #991b1b)' },
};

const StatusBadge = ({ status }) => (
  <span style={{
    display: 'inline-block', padding: '2px 10px', borderRadius: '999px',
    fontSize: '12px', fontWeight: 600, textTransform: 'capitalize',
    ...(STATUS_STYLES[status] || STATUS_STYLES.processing),
  }}>
    {status}
  </span>
);

export default function AnalyticsScreen() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['liveAnalytics'],
    queryFn: async () => {
      const res = await fetch('/api/analytics/live');
      if (!res.ok) throw new Error(`Analytics service returned ${res.status}`);
      return res.json();
    },
    refetchInterval: POLL_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });

  const sessions = data?.sessions || [];

  return (
    <>
      <header className="topbar">
        <div className="tb-title">
          <h1 className="tb-h1">Analytics</h1>
          <div className="tb-crumb">
            <span>Reports</span>
            <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
            <span>Analytics</span>
          </div>
        </div>
      </header>
      <div className="page-body">
        <div className="panel">
          <div className="panel-head">
            <h2 className="panel-title">Live Processing Analytics</h2>
            <span style={{ fontSize: '12px', color: 'var(--slate)' }}>
              Updates every {POLL_INTERVAL_MS / 1000}s — not stored, reflects current activity only
            </span>
          </div>
          {isLoading ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--slate)' }}>Loading live metrics...</div>
          ) : error ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--danger)' }}>Failed to reach analytics service</div>
          ) : sessions.length === 0 ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--slate)' }}>No processing activity yet. Upload a tender document to see live metrics here.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Filename</th>
                    <th>Status</th>
                    <th>Groups Done</th>
                    <th>Elapsed (s)</th>
                    <th>Tokens In</th>
                    <th>Tokens Out</th>
                    <th>Cache Read</th>
                    <th>Cache Write</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map(s => (
                    <tr key={s.id}>
                      <td>{s.filename}</td>
                      <td><StatusBadge status={s.status} /></td>
                      <td>{s.groupsDone}/{s.groupsTotal}</td>
                      <td>{s.elapsedSec}s</td>
                      <td>{s.inputTokens || 0}</td>
                      <td>{s.outputTokens || 0}</td>
                      <td>{s.cacheReadTokens || 0}</td>
                      <td>{s.cacheWriteTokens || 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
