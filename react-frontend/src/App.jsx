import React, { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTenders } from './hooks/useTenders.js';
import { downloadTender, deleteTender, getTenderDocuments } from './api/tenderApi.js';
import LoginScreen from './components/LoginScreen';
import DashboardScreen from './components/DashboardScreen';
import DetailsScreen from './components/DetailsScreen';
import ChatbotPanel from './components/ChatbotPanel';

function App() {
  const [user,           setUser]           = useState('admin'); // Default local mock user
  const [screen,         setScreen]         = useState('dashboard'); // bypass login
  const [selectedTender, setSelectedTender] = useState(null);
  const [isDetailsPreEditing, setIsDetailsPreEditing] = useState(false);

  // Chatbot state — tracks which tender the chatbot is opened for (null = global)
  const [isChatOpen,     setIsChatOpen]     = useState(false);
  const [chatTenderId,   setChatTenderId]   = useState(null);
  const [chatMode,       setChatMode]       = useState('normal'); // 'normal' | 'followup'

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
    setChatMode('normal');
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
    setChatMode('normal');
    setIsChatOpen(true);
  };

  const handleOpenFollowUp = (tender) => {
    setChatTenderId(tender?.id || null);
    setChatMode('followup');
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
        <div className={`app-container ${isChatOpen ? 'chat-open' : ''}`}>
          {screen === 'dashboard' && (
            <DashboardScreen
              username={user}
              tenders={tenders}
              loading={loading}
              error={error}
              onLogout={handleLogout}
              onShowDetails={handleShowDetails}
              onOpenChat={handleOpenChat}
              onOpenFollowUp={handleOpenFollowUp}
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

          {/* Floating chatbot button — visible when chat is closed */}
          <button
            onClick={() => handleOpenChat(selectedTender)}
            className="btn btn-primary"
            style={{
              position: 'fixed', bottom: '30px', right: '30px', borderRadius: '99px',
              width: '60px', height: '60px', padding: 0, boxShadow: 'var(--shadow-lg)', zIndex: 40,
              display: isChatOpen ? 'none' : 'flex', alignItems: 'center', justifyContent: 'center',
            }}
            title="Open Copilot"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
          </button>

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
            mode={chatMode}
            setMode={setChatMode}
            tenders={tenders}
          />
        </div>
      )}
    </>
  );
}

export default App;
