import React, { useState } from 'react';
import RemarksModal from './RemarksModal';
import StatusBadge from './StatusBadge';

export default function DashboardScreen({
  tenders,
  loading,
  error,
  onShowDetails,
  onOpenChat,
  onPrefetchDocuments,
  onDelete,
}) {
  const [remarksTarget, setRemarksTarget] = useState(null);
  const [searchQuery,   setSearchQuery]   = useState('');

  const filteredTenders = tenders.filter((t) => {
    if (!searchQuery) return true;
    const q = searchQuery.trim().toLowerCase();
    return (
      (t.tenderNo || '').toLowerCase().includes(q) ||
      (t.title    || '').toLowerCase().includes(q)
    );
  });

  return (
    <>
      {/* ── Topbar ─────────────────────────────────────────────── */}
      <header className="topbar">
        <div className="tb-title">
          <h1 className="tb-h1">Tenders</h1>
          <div className="tb-crumb">
            <span>Procurement</span>
            <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
            <span>Active Tenders</span>
          </div>
        </div>
        <div className="tb-acts">
          <button
            className="btn btn-sec"
            onClick={() => onOpenChat()}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="17 8 12 3 7 8"/>
              <line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
            Upload PDF
          </button>
          <button
            className="btn btn-ai"
            onClick={() => onOpenChat()}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            AI Copilot
          </button>
        </div>
      </header>

      {/* ── Page body ──────────────────────────────────────────── */}
      <div className="page-body">
        {error && (
          <div className="error-msg" style={{ marginBottom: '16px' }}>
            ⚠️ {error} — showing local data if available.
          </div>
        )}

        <div className="panel">
          {/* Panel header */}
          <div className="panel-head">
            <span className="panel-title">Active Tenders</span>
            <span className="count-chip">{filteredTenders.length}</span>
            <div style={{ flex: 1 }} />

            {/* Search */}
            <div className="srch-wrap">
              <svg className="srch-ico" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <circle cx="11" cy="11" r="8"/>
                <line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <input
                type="text"
                className="srch-in"
                placeholder="Search by tender no…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                aria-label="Search tenders"
              />
              {searchQuery && (
                <button
                  className="srch-clear"
                  onClick={() => setSearchQuery('')}
                  title="Clear search"
                  aria-label="Clear search"
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                  </svg>
                </button>
              )}
            </div>

            <button
              onClick={() => setRemarksTarget('all')}
              className="btn btn-ghost"
              style={{ fontSize: '12.5px', padding: '5px 11px' }}
            >
              All Remarks
            </button>
          </div>

          {/* Skeleton loader */}
          {loading && (
            <div className="tbl-wrap">
              <table className="tbl" style={{ minWidth: '700px' }}>
                <tbody>
                  {Array.from({ length: 6 }).map((_, i) => (
                    <tr key={i}>
                      {[140, 240, 90, 40, 90, 90, 120].map((w, j) => (
                        <td key={j} style={{ padding: '12px 14px' }}>
                          <div style={{
                            height: '13px', borderRadius: '4px', width: `${w}px`, maxWidth: '100%',
                            background: 'linear-gradient(90deg, var(--edge-lt) 25%, #e4e6f0 50%, var(--edge-lt) 75%)',
                            backgroundSize: '400% 100%',
                            animation: 'shimmer 1.4s ease infinite',
                            animationDelay: `${(i * 7 + j) * 0.03}s`,
                          }} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Table */}
          {!loading && (
            <div className="tbl-wrap">
              <table className="tbl" style={{ minWidth: '700px' }} aria-label="Tender list">
                <thead>
                  <tr>
                    <th scope="col">Tender No</th>
                    <th scope="col">Title</th>
                    <th scope="col">Status</th>
                    <th scope="col">Ver</th>
                    <th scope="col">Created By</th>
                    <th scope="col">Last Reviewed</th>
                    <th scope="col" style={{ textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTenders.map((t) => (
                    <tr
                      key={t.id}
                      onMouseEnter={() => onPrefetchDocuments?.(t.id)}
                      onClick={() => onShowDetails(t)}
                      title="Click to view details"
                    >
                      <td><span className="t-no">{t.tenderNo || t.id}</span></td>
                      <td><span className="t-title">{t.title}</span></td>
                      <td><StatusBadge status={t.details?.status} /></td>
                      <td><span className="t-ver">v{t.version}</span></td>
                      <td className="t-user">{t.createdBy}</td>
                      <td className="t-user">{t.lastReviewedBy || '—'}</td>
                      <td
                        onClick={(e) => e.stopPropagation()}
                        style={{ cursor: 'default' }}
                      >
                        <div className="row-acts">
                          <button
                            className="ract"
                            onClick={() => onShowDetails(t)}
                          >
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                              <circle cx="12" cy="12" r="3"/>
                            </svg>
                            Details
                          </button>
                          <button
                            className="ract"
                            onClick={() => setRemarksTarget(t)}
                          >
                            Remarks
                          </button>
                          <button
                            className="ract ract-ai"
                            onClick={() => onOpenChat(t)}
                          >
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                            </svg>
                            Copilot
                          </button>
                          {onDelete && (
                            <button
                              className="ract ract-del"
                              onClick={() => onDelete(t)}
                              title="Delete tender"
                              aria-label={`Delete ${t.tenderNo || t.id}`}
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
                                <polyline points="3 6 5 6 21 6"/>
                                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                                <path d="M10 11v6M14 11v6"/>
                                <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
                              </svg>
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {filteredTenders.length === 0 && (
                    <tr>
                      <td colSpan="7" className="tbl-empty">No tenders found.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Remarks Modal */}
      {remarksTarget && (
        <RemarksModal
          tenders={tenders}
          filterTenderId={remarksTarget === 'all' ? null : remarksTarget.id}
          onClose={() => setRemarksTarget(null)}
        />
      )}
    </>
  );
}
