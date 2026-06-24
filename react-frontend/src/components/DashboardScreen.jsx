import React, { useState } from 'react';
import RemarksModal from './RemarksModal';

export default function DashboardScreen({
  username,
  tenders,
  loading,
  error,
  onLogout,
  onShowDetails,
  onOpenChat,
}) {
  const [remarksTarget, setRemarksTarget] = useState(null); // null = closed, 'all' = global, tender obj = per-row
  const [searchQuery, setSearchQuery] = useState('');

  const filteredTenders = tenders.filter((t) => {
    if (!searchQuery) return true;
    const query = searchQuery.trim().toLowerCase();
    const tNo = (t.tenderNo || '').toLowerCase();
    const tId = (t.id || '').toLowerCase();
    return tNo.includes(query) || tId.includes(query);
  });

  const btnStyle = {
    padding: '4px 10px',
    fontSize: '12px',
    border: '1px solid var(--border-color)',
    lineHeight: 1.4,
  };

  const statusBadgeStyle = (status) => {
    const map = {
      Draft:    { background: '#fef9c3', color: '#92400e', border: '1px solid #fde68a' },
      Reviewed: { background: '#dbeafe', color: '#1e40af', border: '1px solid #bfdbfe' },
      Approved: { background: '#d1fae5', color: '#065f46', border: '1px solid #a7f3d0' },
    };
    return {
      display: 'inline-block',
      padding: '2px 10px',
      borderRadius: '99px',
      fontSize: '12px',
      fontWeight: 600,
      ...(map[status] || { background: '#f3f4f6', color: '#374151', border: '1px solid #e5e7eb' }),
    };
  };

  return (
    <div className="dashboard-wrapper">
      <main className="main-content">
        {/* Top Navigation */}
        <header className="top-nav">
          <h1>TenderFlow Dashboard</h1>
          <div className="nav-actions">
            <div className="user-badge">
              <div className="user-avatar">{username.charAt(0).toUpperCase()}</div>
              {username}
            </div>
            <button onClick={onLogout} className="btn btn-ghost" style={{ color: 'var(--danger)' }}>
              Sign out
            </button>
          </div>
        </header>

        {/* Data Table Area */}
        <div className="panel">
          <div className="table-header" style={{ padding: '20px 24px 0', flexWrap: 'wrap', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flex: 1, minWidth: '280px' }}>
              <h2>Active Tenders</h2>
              <div className="search-bar-wrapper" style={{ position: 'relative', width: '240px' }}>
                <input
                  type="text"
                  placeholder="Search by tender ID..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="search-input"
                  style={{
                    padding: '8px 12px 8px 36px',
                    fontSize: '13px',
                    width: '100%',
                    border: '1px solid var(--border-color)',
                    borderRadius: 'var(--radius-md)',
                    backgroundColor: 'var(--bg-page)',
                    outline: 'none',
                    transition: 'all 0.15s ease-in-out',
                  }}
                  onFocus={(e) => {
                    e.target.style.borderColor = 'var(--primary)';
                    e.target.style.backgroundColor = 'var(--bg-card)';
                    e.target.style.boxShadow = '0 0 0 3px rgba(37, 99, 235, 0.1)';
                  }}
                  onBlur={(e) => {
                    e.target.style.borderColor = 'var(--border-color)';
                    e.target.style.backgroundColor = 'var(--bg-page)';
                    e.target.style.boxShadow = 'none';
                  }}
                />
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="var(--text-muted)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  style={{
                    position: 'absolute',
                    left: '12px',
                    top: '50%',
                    transform: 'translateY(-50%)',
                    pointerEvents: 'none'
                  }}
                >
                  <circle cx="11" cy="11" r="8"></circle>
                  <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    style={{
                      position: 'absolute',
                      right: '10px',
                      top: '50%',
                      transform: 'translateY(-50%)',
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      color: 'var(--text-muted)',
                      padding: 0,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                    title="Clear search"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18"></line>
                      <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                  </button>
                )}
              </div>
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <button
                onClick={() => onOpenChat()}
                className="btn btn-secondary"
                style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="17 8 12 3 7 8"></polyline>
                  <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg>
                Upload
              </button>
              <button onClick={() => setRemarksTarget('all')} className="btn btn-secondary">
                All Remarks
              </button>
            </div>
          </div>

          <div className="data-table-container" style={{ padding: '20px' }}>
            {loading && (
              <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                Loading tenders from CAP backend…
              </div>
            )}

            {!loading && error && (
              <div className="error-msg" style={{ margin: '16px 0' }}>
                ⚠️ {error} — showing local data if available.
              </div>
            )}

            {!loading && (
              <div style={{ overflowX: 'auto' }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Tender No</th>
                      <th>Version</th>
                      <th>Title</th>
                      <th>Status</th>
                      <th>Created By</th>
                      <th>Last Reviewed</th>
                      <th>Last Changed</th>
                      <th style={{ textAlign: 'right' }}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredTenders.map((t) => (
                      <tr
                        key={t.id}
                        onClick={() => onShowDetails(t)}
                        style={{ cursor: 'pointer' }}
                        title="Click row to view details"
                      >
                        <td style={{ fontWeight: 500 }}>{t.tenderNo || t.id}</td>
                        <td>v{t.version}</td>
                        <td>{t.title}</td>
                        <td>
                          <span style={statusBadgeStyle(t.details?.status)}>
                            {t.details?.status || '—'}
                          </span>
                        </td>
                        <td>{t.createdBy}</td>
                        <td>{t.lastReviewedBy}</td>
                        <td>{t.lastChangedBy}</td>
                        <td onClick={(e) => e.stopPropagation()} style={{ textAlign: 'right', whiteSpace: 'nowrap', cursor: 'default' }}>
                          <div style={{ display: 'inline-flex', gap: '4px', alignItems: 'center' }}>
                            <button onClick={(e) => { e.stopPropagation(); onShowDetails(t); }} className="btn btn-secondary" style={btnStyle}>
                              Details
                            </button>
                            <button onClick={(e) => { e.stopPropagation(); setRemarksTarget(t); }} className="btn btn-ghost" style={btnStyle}>
                              Remarks
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {filteredTenders.length === 0 && !loading && (
                      <tr>
                        <td colSpan="8" style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)' }}>
                          No tenders found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Remarks Modal — per-row or global */}
      {remarksTarget && (
        <RemarksModal
          tenders={tenders}
          filterTenderId={remarksTarget === 'all' ? null : remarksTarget.id}
          onClose={() => setRemarksTarget(null)}
        />
      )}
    </div>
  );
}
