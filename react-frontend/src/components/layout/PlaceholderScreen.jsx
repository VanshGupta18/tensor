import React from 'react';

const PLACEHOLDER_META = {
  overview:  { title: 'Overview',   crumb: 'Workspace',  icon: 'M3 3h7v7H3zm11 0h7v7h-7zM3 14h7v7H3zm11 0h7v7h-7z', desc: 'Summary dashboards and KPI tiles will appear here.' },
  documents: { title: 'Documents',  crumb: 'Workspace',  icon: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z', desc: 'Uploaded PDFs and attachments across all tenders will appear here.' },
  analytics: { title: 'Analytics',  crumb: 'Reports',    icon: 'M18 20V10M12 20V4M6 20v-6', desc: 'Spend analysis, tender lifecycle metrics, and approval trends will appear here.' },
  settings:  { title: 'Settings',   crumb: 'System',     icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', desc: 'User preferences, integrations, and team permissions will appear here.' },
};

export default function PlaceholderScreen({ screen }) {
  const m = PLACEHOLDER_META[screen] || PLACEHOLDER_META.overview;
  return (
    <>
      <header className="topbar">
        <div className="tb-title">
          <h1 className="tb-h1">{m.title}</h1>
          <div className="tb-crumb">
            <span>{m.crumb}</span>
            <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
            <span>{m.title}</span>
          </div>
        </div>
      </header>
      <div className="page-body">
        <div className="panel" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '340px', gap: '16px', color: 'var(--slate)' }}>
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" opacity="0.4" aria-hidden="true">
            <path d={m.icon}/>
          </svg>
          <div style={{ fontWeight: 600, fontSize: '15px', color: 'var(--ink)' }}>{m.title}</div>
          <div style={{ fontSize: '13px', maxWidth: '320px', textAlign: 'center', lineHeight: 1.6 }}>{m.desc}</div>
          <div style={{ fontSize: '11px', marginTop: '4px', letterSpacing: '0.04em', textTransform: 'uppercase', opacity: 0.5 }}>Coming soon</div>
        </div>
      </div>
    </>
  );
}
