import React, { useState, Suspense } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTenders } from './hooks/useTenders.js';
import { downloadTender, deleteTender, getTenderDocuments } from './api/tenderApi.js';
import Sidebar from './components/Sidebar';

const LoginScreen = React.lazy(() => import('./components/LoginScreen'));
const DashboardScreen = React.lazy(() => import('./components/DashboardScreen'));
const DetailsScreen = React.lazy(() => import('./components/DetailsScreen'));
const ChatbotPanel = React.lazy(() => import('./components/ChatbotPanel'));
const AnalyticsScreen = React.lazy(() => import('./components/layout/AnalyticsScreen.jsx'));

function App() {
  const [user,           setUser]           = useState('admin'); // Default local mock user
  const [screen,         setScreen]         = useState('dashboard'); // bypass login
  const [selectedTender, setSelectedTender] = useState(null);
  const [isDetailsPreEditing, setIsDetailsPreEditing] = useState(false);

  // Chatbot state — tracks which tender the chatbot is opened for (null = global)
  const [isChatOpen,   setIsChatOpen]   = useState(false);
  const [chatTenderId, setChatTenderId] = useState(null);
  
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

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
    setIsSidebarCollapsed(true);
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
    <Suspense fallback={<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--slate)' }}>Loading...</div>}>
      {screen === 'login' && (
        <LoginScreen onLoginSuccess={handleLoginSuccess} />
      )}

      {screen !== 'login' && (
        <div className={`app-shell ${isChatOpen ? 'chat-open' : ''} ${isSidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
          <Sidebar
            username={user}
            tenderCount={tenders.length}
            currentScreen={screen}
            isCollapsed={isSidebarCollapsed}
            onToggle={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            onLogout={handleLogout}
            onNavigate={(s) => setScreen(s)}
          />

          <div className="main-area">
            <Suspense fallback={<div style={{ padding: '24px', color: 'var(--slate)' }}>Loading Screen...</div>}>
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

              {screen === 'analytics' && (
                <AnalyticsScreen />
              )}
            </Suspense>
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

          <Suspense fallback={null}>
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
          </Suspense>
        </div>
      )}
    </Suspense>
  );
}

export default App;
