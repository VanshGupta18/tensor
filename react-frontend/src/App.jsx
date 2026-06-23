import React, { useState } from 'react';
import { useTenders } from './hooks/useTenders.js';
import { downloadTender, deleteTender } from './api/tenderApi.js';
import LoginScreen from './components/LoginScreen';
import DashboardScreen from './components/DashboardScreen';
import DetailsScreen from './components/DetailsScreen';
import ChatbotPanel from './components/ChatbotPanel';

function App() {
  const [user,           setUser]           = useState(null);
  const [screen,         setScreen]         = useState('login'); // 'login' | 'dashboard' | 'details'
  const [selectedTender, setSelectedTender] = useState(null);
  const [isDetailsPreEditing, setIsDetailsPreEditing] = useState(false);

  // Chatbot state — tracks which tender the chatbot is opened for (null = global)
  const [isChatOpen,     setIsChatOpen]     = useState(false);
  const [chatTenderId,   setChatTenderId]   = useState(null);

  const {
    tenders,
    loading,
    error,
    refresh,
    handleMarkReviewed,
    handleSaveChanges,
  } = useTenders(user);

  // ── Auth ───────────────────────────────────────────────────────────────────
  const handleLoginSuccess = (username) => {
    setUser(username);
    setScreen('dashboard');
  };

  const handleLogout = () => {
    setUser(null);
    setScreen('login');
    setIsChatOpen(false);
    setChatTenderId(null);
    setSelectedTender(null);
  };

  // ── Navigation ──────────────────────────────────────────────────────────────
  const handleShowDetails = async (tender) => {
    const updated = await handleMarkReviewed(tender);
    setSelectedTender(updated);
    setIsDetailsPreEditing(false);
    setScreen('details');
  };

  const handleEditDetails = async (tender) => {
    const updated = await handleMarkReviewed(tender);
    setSelectedTender(updated);
    setIsDetailsPreEditing(true);
    setScreen('details');
  };

  // ── Open chatbot for a specific tender row (or globally) ────────────────────
  const handleOpenChat = (tender) => {
    setChatTenderId(tender?.id || null);
    setIsChatOpen(true);
  };

  // ── Save changes ────────────────────────────────────────────────────────────
  const onSaveChanges = async (tenderId, updatedFormValues, changedList, remarksObject) => {
    try {
      const updated = await handleSaveChanges(tenderId, updatedFormValues, changedList, remarksObject);
      setSelectedTender(updated);
    } catch (err) {
      console.error('Save failed:', err);
    }
  };

  const handleDownloadDetails = (tender) => downloadTender(tender);

  const handleDelete = async (tender) => {
    const label = tender.tenderNo || tender.id;
    if (!window.confirm(`Delete tender "${label}"? This cannot be undone.`)) return;
    try {
      await deleteTender(tender.id);
      refresh();
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
              onEditDetails={handleEditDetails}
              onDownload={handleDownloadDetails}
              onOpenChat={handleOpenChat}
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
            onUploadComplete={refresh}
          />
        </div>
      )}
    </>
  );
}

export default App;
