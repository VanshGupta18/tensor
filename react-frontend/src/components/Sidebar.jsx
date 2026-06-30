import React from 'react';

export default function Sidebar({ username, tenderCount, currentScreen, onLogout, onNavigate }) {
  return (
    <aside className="sidebar">
      <div className="sb-brand">
        <div className="sb-mark">TF</div>
        <div className="sb-wordmark">
          <div className="sb-name">TenderFlow</div>
          <div className="sb-sub">Procurement Suite</div>
        </div>
      </div>

      <nav className="sb-nav">
        <span className="sb-section">Workspace</span>

        <button
          className={`sb-item ${currentScreen === 'overview' ? 'active' : ''}`}
          onClick={() => onNavigate('overview')}
          aria-current={currentScreen === 'overview' ? 'page' : undefined}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <rect x="3" y="3" width="7" height="7"/>
            <rect x="14" y="3" width="7" height="7"/>
            <rect x="3" y="14" width="7" height="7"/>
            <rect x="14" y="14" width="7" height="7"/>
          </svg>
          Overview
        </button>

        <button
          className={`sb-item ${currentScreen === 'dashboard' || currentScreen === 'details' ? 'active' : ''}`}
          onClick={() => onNavigate('dashboard')}
          aria-current={currentScreen === 'dashboard' ? 'page' : undefined}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          Tenders
          {tenderCount > 0 && <span className="sb-count">{tenderCount}</span>}
        </button>

        <button
          className={`sb-item ${currentScreen === 'documents' ? 'active' : ''}`}
          onClick={() => onNavigate('documents')}
          aria-current={currentScreen === 'documents' ? 'page' : undefined}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
          Documents
        </button>

        <span className="sb-section">Reports</span>

        <button
          className={`sb-item ${currentScreen === 'analytics' ? 'active' : ''}`}
          onClick={() => onNavigate('analytics')}
          aria-current={currentScreen === 'analytics' ? 'page' : undefined}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <line x1="18" y1="20" x2="18" y2="10"/>
            <line x1="12" y1="20" x2="12" y2="4"/>
            <line x1="6" y1="20" x2="6" y2="14"/>
          </svg>
          Analytics
        </button>

        <span className="sb-section">System</span>

        <button
          className={`sb-item ${currentScreen === 'settings' ? 'active' : ''}`}
          onClick={() => onNavigate('settings')}
          aria-current={currentScreen === 'settings' ? 'page' : undefined}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06-.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
          Settings
        </button>
      </nav>

      <div className="sb-foot">
        <div className="sb-ava" aria-hidden="true">
          {username ? username.charAt(0).toUpperCase() : '?'}
        </div>
        <div className="sb-user">
          <div className="sb-uname">{username || 'User'}</div>
          <div className="sb-urole">Administrator</div>
        </div>
        <button className="sb-out" onClick={onLogout} title="Sign out" aria-label="Sign out">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
            <polyline points="16 17 21 12 16 7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
        </button>
      </div>
    </aside>
  );
}
