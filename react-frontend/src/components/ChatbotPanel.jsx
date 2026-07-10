import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { streamChatMessage, uploadFileForProcessing, applyTenderUpdate } from '../api/chatApi.js';
import { validatePdfFile } from '../utils/fileUtils.js';
import UploadTimeline from './chat/UploadTimeline.jsx';
import FileResult from './chat/FileResult.jsx';

// ── Main component ────────────────────────────────────────────────────────────

export default function ChatbotPanel({ isOpen, onClose, tenderId = null, onUploadComplete, tenders = [] }) {
  const activeTender = tenders?.find(t => t.id === tenderId);
  const tenderLabel = activeTender ? (activeTender.tenderNo || activeTender.title || '') : '';

  const welcomeText = tenderId
    ? `Ask me anything about this tender, or upload a follow-up PDF to update its information.`
    : `Upload a tender PDF to extract and save its information automatically, or ask a question.`;

  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingType, setProcessingType] = useState(null); // 'chat' | 'upload'
  const [isUploadComplete, setIsUploadComplete] = useState(false);
  const [uploadFilename, setUploadFilename] = useState('');
  const [uploadProgress, setUploadProgress] = useState(null);
  const [confirmStates, setConfirmStates] = useState({});

  const fileInputRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Reset on context change
  useEffect(() => { setMessages([]); }, [tenderId]);

  useEffect(() => {
    // Disabled so user can scroll tender details
    // document.body.style.overflow = isOpen ? 'hidden' : '';
    // return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  const addMessage = (payload, sender) => {
    setMessages(prev => [...prev, {
      id: crypto.randomUUID(),
      sender,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      ...(typeof payload === 'string' ? { text: payload, type: 'text' } : payload),
    }]);
  };

  // ── Confirm / reject duplicate update ────────────────────────────────────────
  const handleConfirm = async (msgId, idx, resultTenderId, patch, changedFields) => {
    setConfirmStates(prev => ({ ...prev, [msgId]: { ...(prev[msgId] || {}), [idx]: 'loading' } }));
    try {
      await applyTenderUpdate(resultTenderId, patch, changedFields);
      setConfirmStates(prev => ({ ...prev, [msgId]: { ...(prev[msgId] || {}), [idx]: 'confirmed' } }));
      if (onUploadComplete) onUploadComplete();
    } catch {
      setConfirmStates(prev => ({ ...prev, [msgId]: { ...(prev[msgId] || {}), [idx]: 'error' } }));
    }
  };

  const handleReject = (msgId, idx) =>
    setConfirmStates(prev => ({ ...prev, [msgId]: { ...(prev[msgId] || {}), [idx]: 'rejected' } }));

  // ── Text chat ─────────────────────────────────────────────────────────────────
  const handleSend = async () => {
    if (!inputText.trim() || isProcessing) return;
    const userQuery = inputText.trim();

    // Capture history before adding the new user message to state
    const history = messages
      .filter(m => m.type === 'text')
      .map(m => ({ role: m.sender === 'user' ? 'user' : 'assistant', content: m.text }));

    addMessage(userQuery, 'user');
    setInputText('');
    setIsProcessing(true);
    setProcessingType('chat');

    const botId = crypto.randomUUID();
    let firstChunk = true;

    try {
      await streamChatMessage(userQuery, tenderId, (chunk) => {
        if (firstChunk) {
          firstChunk = false;
          setIsProcessing(false);
          setMessages(prev => [...prev, {
            id: botId, sender: 'bot', text: chunk, type: 'text', isStreaming: true,
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          }]);
        } else {
          setMessages(prev => prev.map(m => m.id === botId ? { ...m, text: m.text + chunk } : m));
        }
      }, history);
      setMessages(prev => prev.map(m => m.id === botId ? { ...m, isStreaming: false } : m));
    } catch (err) {
      setIsProcessing(false);
      if (firstChunk) {
        addMessage(`Could not reach AI: ${err.message}`, 'bot');
      } else {
        setMessages(prev => prev.map(m =>
          m.id === botId ? { ...m, text: m.text + ' [interrupted]', isStreaming: false } : m
        ));
      }
    } finally {
      setIsProcessing(false);
      setProcessingType(null);
    }
  };

  // ── File upload ───────────────────────────────────────────────────────────────
  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const err = validatePdfFile(file);
    if (err) { addMessage(err, 'bot'); if (fileInputRef.current) fileInputRef.current.value = ''; return; }

    // Client-side cost optimization: Block massive files
    if (file.size > 50 * 1024 * 1024) {
      addMessage('File too large (exceeds 50MB limit). To save processing costs, please split or compress the document.', 'bot');
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }

    setUploadFilename(file.name);
    setUploadProgress(null);
    setIsProcessing(true);
    setIsUploadComplete(false);
    setProcessingType('upload');

    try {
      const raw = await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Timed out after 10 minutes.')), 600_000);
        uploadFileForProcessing(file, tenderId, (job) => {
          if (job?.progress) setUploadProgress(job.progress);
        })
          .then(r => { clearTimeout(timeout); resolve(r); })
          .catch(r => { clearTimeout(timeout); reject(r); });
      });
      const result = typeof raw === 'string' ? JSON.parse(raw) : raw;
      
      // Zip the timeline to 100% and let user see it complete
      setIsUploadComplete(true);
      await new Promise(r => setTimeout(r, 600));

      const msgId = crypto.randomUUID();
      setMessages(prev => [...prev, {
        id: msgId, sender: 'bot', type: 'file-result',
        filename: file.name,
        results: result.results || [],
        message: result.message || '',
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }]);
      if (result.results?.length > 0 && onUploadComplete) onUploadComplete();
    } catch (err) {
      // chatApi.js already formats the message — don't prepend another prefix.
      // e.g. "HTTP 502 — Could not reach the backend" not "Upload failed: Upload failed: …"
      addMessage(err.message, 'bot');
    } finally {
      setIsProcessing(false);
      setProcessingType(null);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <>
      <div className={`chatbot-drawer ${isOpen ? 'open' : ''}`}>

        {/* Header */}
        <div className="chatbot-header">
          <h3 style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
            Copilot
            {tenderLabel && (
              <span style={{ fontSize: '12px', opacity: 0.6, fontWeight: 400 }}>• {tenderLabel}</span>
            )}
          </h3>
          <button onClick={onClose} className="btn btn-ghost" style={{ padding: '4px 8px' }}>✕</button>
        </div>

        {/* Messages */}
        <div className="chatbot-messages">

          {/* Context-aware welcome */}
          <div className="chat-msg bot">
            <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.55', color: 'var(--text-muted)' }}>
              {welcomeText}
            </p>
            {!tenderId && (
              <button
                className="btn btn-primary"
                style={{ marginTop: '12px', display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '13px', padding: '8px 14px' }}
                onClick={() => fileInputRef.current?.click()}
                disabled={isProcessing}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                Upload PDF
              </button>
            )}
          </div>

          {/* Conversation */}
          {messages.map(msg => (
            <div key={msg.id} className={`chat-msg ${msg.sender}`}>
              {msg.type === 'file-result' ? (
                <FileResult
                  filename={msg.filename}
                  results={msg.results}
                  message={msg.message}
                  confirmStates={confirmStates[msg.id] || {}}
                  onConfirm={(idx, tid, patch, fields) => handleConfirm(msg.id, idx, tid, patch, fields)}
                  onReject={(idx) => handleReject(msg.id, idx)}
                />
              ) : (
                <div style={{ margin: 0, fontSize: '14px', lineHeight: '1.55', overflowWrap: 'break-word' }} className="markdown-body">
                  <ReactMarkdown>{msg.isStreaming ? msg.text + '▋' : msg.text}</ReactMarkdown>
                </div>
              )}
              <div className="chat-msg-time">{msg.time}</div>
            </div>
          ))}

          {/* Thinking / upload indicator */}
          {isProcessing && (
            <div className="chat-msg bot">
              {processingType === 'upload' ? (
                <UploadTimeline key={uploadFilename} filename={uploadFilename} progress={uploadProgress} isComplete={isUploadComplete} />
              ) : (
                <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                  {[0, 0.2, 0.4].map((delay, i) => (
                    <span key={i} style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor', animation: `pulse 1s infinite ${delay}s` }} />
                  ))}
                </div>
              )}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="chatbot-input-area">
          <div className="chat-form">
            <input type="file" ref={fileInputRef} style={{ display: 'none' }} onChange={handleUpload} accept=".pdf" />
            <button
              className="chat-file-btn"
              onClick={() => fileInputRef.current?.click()}
              title="Upload PDF"
              disabled={isProcessing}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
              </svg>
            </button>
            <input
              type="text"
              className="chat-input"
              placeholder="Ask a question…"
              value={inputText}
              onChange={e => setInputText(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !isProcessing && handleSend()}
              disabled={isProcessing}
            />
            <button className="btn btn-primary" onClick={handleSend} style={{ padding: '10px 16px' }} disabled={isProcessing}>
              Send
            </button>
          </div>
        </div>
      </div>

      <div className="drawer-overlay" onClick={onClose} />
    </>
  );
}
