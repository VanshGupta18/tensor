import React from 'react';

export default function Sidebar({ username, tenderCount, currentScreen, isCollapsed, onToggle, onNavigate }) {
  return (
    <aside className={`sidebar ${isCollapsed ? 'collapsed' : ''}`}>
      <div className="sb-brand">
        <div className="sb-brand-content">
          <div className="sb-mark">TF</div>
          <div className="sb-wordmark">
            <div className="sb-name">TenderFlow</div>
            <div className="sb-sub">Procurement Suite</div>
          </div>
        </div>
        <button className="sb-toggle" onClick={onToggle} title="Toggle Sidebar" aria-label="Toggle Sidebar">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            {isCollapsed ? <path d="M9 18l6-6-6-6"/> : <path d="M15 18l-6-6 6-6"/>}
          </svg>
        </button>
      </div>

      <nav className="sb-nav">
        <span className="sb-section"><span className="sb-section-text">Workspace</span></span>

        <button
          className={`sb-item ${currentScreen === 'dashboard' || currentScreen === 'details' ? 'active' : ''}`}
          onClick={() => onNavigate('dashboard')}
          aria-current={currentScreen === 'dashboard' ? 'page' : undefined}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          <span className="sb-text">Tenders</span>
        </button>

        <span className="sb-section"><span className="sb-section-text">Reports</span></span>

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
          <span className="sb-text">Analytics</span>
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
      </div>
    </aside>
  );
}
