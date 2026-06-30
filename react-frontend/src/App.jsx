import React, { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTenders } from './hooks/useTenders.js';
import { downloadTender, deleteTender, getTenderDocuments } from './api/tenderApi.js';
import LoginScreen from './components/LoginScreen';
import DashboardScreen from './components/DashboardScreen';
import DetailsScreen from './components/DetailsScreen';
import ChatbotPanel from './components/ChatbotPanel';
import Sidebar from './components/Sidebar';

const PLACEHOLDER_META = {
  overview:  { title: 'Overview',   crumb: 'Workspace',  icon: 'M3 3h7v7H3zm11 0h7v7h-7zM3 14h7v7H3zm11 0h7v7h-7z', desc: 'Summary dashboards and KPI tiles will appear here.' },
  documents: { title: 'Documents',  crumb: 'Workspace',  icon: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z', desc: 'Uploaded PDFs and attachments across all tenders will appear here.' },
  analytics: { title: 'Analytics',  crumb: 'Reports',    icon: 'M18 20V10M12 20V4M6 20v-6', desc: 'Spend analysis, tender lifecycle metrics, and approval trends will appear here.' },
  settings:  { title: 'Settings',   crumb: 'System',     icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', desc: 'User preferences, integrations, and team permissions will appear here.' },
};

function PlaceholderScreen({ screen }) {
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

function App() {
  const [user,           setUser]           = useState('admin'); // Default local mock user
  const [screen,         setScreen]         = useState('dashboard'); // bypass login
  const [selectedTender, setSelectedTender] = useState(null);
  const [isDetailsPreEditing, setIsDetailsPreEditing] = useState(false);

  // Chatbot state — tracks which tender the chatbot is opened for (null = global)
  const [isChatOpen,   setIsChatOpen]   = useState(false);
  const [chatTenderId, setChatTenderId] = useState(null);

  const queryClient = useQueryClient();

  const {
    tenders,
    loading,
    error,
    handleMarkReviewed,
    handleSaveChanges,
  } = useTenders(user);

  // ── Auth ───────────────────────────────────────────────────────────────────
  // Restore session on mount
  React.useEffect(() => {
    const token = localStorage.getItem('token');
    const savedUser = localStorage.getItem('username');
    if (token && savedUser) {
      setUser(savedUser);
      setScreen('dashboard');
    }
  }, []);

  const handleLoginSuccess = (username) => {
    setUser(username);
    localStorage.setItem('username', username);
    setScreen('dashboard');
  };

  const handleLogout = () => {
    setUser(null);
    localStorage.removeItem('token');
    localStorage.removeItem('username');
    setScreen('login');
    setIsChatOpen(false);
    setChatTenderId(null);
    setSelectedTender(null);
  };

  // ── Navigation ──────────────────────────────────────────────────────────────
  const handleShowDetails = (tender) => {
    setSelectedTender(tender);
    setIsDetailsPreEditing(false);
    setScreen('details');
    // Mark reviewed in background — don't block navigation
    handleMarkReviewed(tender)
      .then(updated => setSelectedTender(prev => prev?.id === updated.id ? updated : prev))
      .catch(() => {});
  };

  // ── Open chatbot for a specific tender row (or globally) ────────────────────
  const handleOpenChat = (tender) => {
    setChatTenderId(tender?.id || null);
    setIsChatOpen(true);
  };

  // ── Save changes ────────────────────────────────────────────────────────────
  const onSaveChanges = async (tenderId, updatedFormValues, changedList, remarksObject) => {
    await handleSaveChanges(tenderId, updatedFormValues, changedList, remarksObject);
    const updated = queryClient.getQueryData(['tenders'])?.find(t => t.id === tenderId);
    if (updated) setSelectedTender(updated);
  };

  const handlePrefetchDocuments = (tenderId) =>
    queryClient.prefetchQuery({
      queryKey: ['tender', tenderId, 'documents'],
      queryFn: () => getTenderDocuments(tenderId),
      staleTime: 5 * 60 * 1000,
    });

  const handleDownloadDetails = async (tender) => {
    try {
      await downloadTender(tender);
    } catch (err) {
      alert(err.message);
    }
  };

  const handleDelete = async (tender) => {
    const label = tender.tenderNo || tender.id;
    if (!window.confirm(`Delete tender "${label}"? This cannot be undone.`)) return;
    try {
      await deleteTender(tender.id);
      queryClient.invalidateQueries({ queryKey: ['tenders'] });
      setScreen('dashboard');
    } catch (err) {
      alert('Delete failed: ' + err.message);
    }
  };

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <>
      {screen === 'login' && (
        <LoginScreen onLoginSuccess={handleLoginSuccess} />
      )}

      {screen !== 'login' && (
        <div className={`app-shell ${isChatOpen ? 'chat-open' : ''}`}>
          <Sidebar
            username={user}
            tenderCount={tenders.length}
            currentScreen={screen}
            onLogout={handleLogout}
            onNavigate={(s) => setScreen(s)}
          />

          <div className="main-area">
            {screen === 'dashboard' && (
              <DashboardScreen
                username={user}
                tenders={tenders}
                loading={loading}
                error={error}
                onLogout={handleLogout}
                onShowDetails={handleShowDetails}
                onOpenChat={handleOpenChat}
                onPrefetchDocuments={handlePrefetchDocuments}
                onDelete={handleDelete}
              />
            )}

            {screen === 'details' && selectedTender && (
              <DetailsScreen
                tender={selectedTender}
                initialIsEditing={isDetailsPreEditing}
                onBack={() => setScreen('dashboard')}
                onSaveChanges={onSaveChanges}
                onOpenChat={() => handleOpenChat(selectedTender)}
                onDownload={handleDownloadDetails}
              />
            )}

            {['overview', 'documents', 'analytics', 'settings'].includes(screen) && (
              <PlaceholderScreen screen={screen} />
            )}
          </div>

          {/* Floating AI Copilot button */}
          {!isChatOpen && (
            <button
              onClick={() => handleOpenChat(selectedTender)}
              className="fab"
              title="Open AI Copilot"
              aria-label="Open AI Copilot"
            >
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
              </svg>
            </button>
          )}

          {/* Chatbot Drawer */}
          <ChatbotPanel
            isOpen={isChatOpen}
            onClose={() => setIsChatOpen(false)}
            tenderId={chatTenderId}
            onUploadComplete={() => {
                queryClient.invalidateQueries({ queryKey: ['tenders'] });
                if (chatTenderId) {
                  queryClient.invalidateQueries({ queryKey: ['tender', chatTenderId, 'documents'] });
                }
              }}
            tenders={tenders}
          />
        </div>
      )}
    </>
  );
}

export default App;
