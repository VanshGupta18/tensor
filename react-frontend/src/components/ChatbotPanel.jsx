import React, { useState, useRef, useEffect } from 'react';
import { sendChatMessage, uploadFileForProcessing, applyTenderUpdate } from '../api/chatApi.js';

// ── Inline markdown renderer ──────────────────────────────────────────────────
// Handles: **bold**, bullet lists (- / *), numbered lists, blank-line paragraphs.
function MarkdownText({ text }) {
  if (!text) return null;

  const lines = text.split('\n');
  const elements = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Blank line → spacer
    if (line.trim() === '') {
      elements.push(<div key={i} style={{ height: '6px' }} />);
      i++;
      continue;
    }

    // Bullet list item  (- text  or  * text)
    const bulletMatch = line.match(/^(\s*[-*])\s+(.+)/);
    if (bulletMatch) {
      const listItems = [];
      while (i < lines.length && lines[i].match(/^(\s*[-*])\s+(.+)/)) {
        const m = lines[i].match(/^(\s*[-*])\s+(.+)/);
        listItems.push(<li key={i}>{renderInline(m[2])}</li>);
        i++;
      }
      elements.push(
        <ul key={`ul-${i}`} style={{ margin: '4px 0', paddingLeft: '20px' }}>
          {listItems}
        </ul>
      );
      continue;
    }

    // Numbered list  (1. text)
    const numMatch = line.match(/^\d+\.\s+(.+)/);
    if (numMatch) {
      const listItems = [];
      while (i < lines.length && lines[i].match(/^\d+\.\s+(.+)/)) {
        const m = lines[i].match(/^\d+\.\s+(.+)/);
        listItems.push(<li key={i}>{renderInline(m[1])}</li>);
        i++;
      }
      elements.push(
        <ol key={`ol-${i}`} style={{ margin: '4px 0', paddingLeft: '20px' }}>
          {listItems}
        </ol>
      );
      continue;
    }

    // Regular paragraph line
    elements.push(<p key={i} style={{ margin: '2px 0' }}>{renderInline(line)}</p>);
    i++;
  }

  return <div style={{ lineHeight: '1.55', fontSize: '14px' }}>{elements}</div>;
}

// Render inline formatting: **bold**, *italic*, `code`
function renderInline(text) {
  const parts = [];
  // Split on **bold**, *italic*, or `code`
  const regex = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g;
  let last = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));

    if (match[0].startsWith('**')) {
      parts.push(<strong key={match.index}>{match[2]}</strong>);
    } else if (match[0].startsWith('*')) {
      parts.push(<em key={match.index}>{match[3]}</em>);
    } else if (match[0].startsWith('`')) {
      parts.push(
        <code key={match.index} style={{ background: 'rgba(0,0,0,0.08)', padding: '1px 4px', borderRadius: '3px', fontSize: '12px' }}>
          {match[4]}
        </code>
      );
    }
    last = match.index + match[0].length;
  }

  if (last < text.length) parts.push(text.slice(last));
  return parts.length === 1 && typeof parts[0] === 'string' ? parts[0] : parts;
}

// ── File upload result renderer ───────────────────────────────────────────────
function FileResultMessage({ filename, results, message, confirmStates, onConfirm, onReject }) {
  if (!results || results.length === 0) {
    return (
      <div>
        <div style={{ fontWeight: 600, marginBottom: '6px' }}>📄 {filename}</div>
        <div style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
          ℹ️ {message || 'No tender information found in this document.'}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ fontWeight: 600, marginBottom: '10px' }}>📄 {filename}</div>
      {results.map((r, i) => {
        const confirmState = confirmStates?.[i]; // 'pending' | 'loading' | 'confirmed' | 'rejected'

        // ── Duplicate found — needs confirmation ──────────────────────────────
        if (r.requiresConfirmation) {
          return (
            <div key={i} style={{
              marginBottom: '10px', padding: '10px 12px', borderRadius: '8px',
              border: '1px solid #fbbf24', background: '#fffbeb',
            }}>
              <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '4px', color: '#92400e' }}>
                ⚠️ Duplicate tender found
              </div>
              <div style={{ fontSize: '13px', fontWeight: 500, marginBottom: '4px' }}>{r.title}</div>
              {r.tenderNo && (
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Ref: {r.tenderNo}
                </div>
              )}
              <div style={{ fontSize: '12px', marginBottom: '10px', color: '#78350f' }}>
                A tender with this reference already exists. Do you want to update it with the information from this PDF?
              </div>

              {confirmState === 'confirmed' && (
                <div style={{ fontSize: '12px', color: '#065f46', fontWeight: 500 }}>✅ Tender updated successfully.</div>
              )}
              {confirmState === 'rejected' && (
                <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>❌ Update cancelled — no changes made.</div>
              )}
              {confirmState === 'error' && (
                <div style={{ fontSize: '12px', color: '#dc2626' }}>⚠️ Failed to apply update. Please try again.</div>
              )}
              {(!confirmState || confirmState === 'loading') && (
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <span style={{ fontSize: '12px', color: '#92400e' }}>Update tender info and data?</span>
                  <button
                    onClick={() => onConfirm(i, r.tenderId, r.pendingPatch, r.changedFields)}
                    disabled={confirmState === 'loading'}
                    style={{ fontSize: '12px', padding: '4px 12px', borderRadius: '6px', border: 'none', background: '#059669', color: '#fff', cursor: 'pointer', fontWeight: 600 }}
                  >
                    {confirmState === 'loading' ? 'Updating…' : 'Yes, update'}
                  </button>
                  <button
                    onClick={() => onReject(i)}
                    disabled={confirmState === 'loading'}
                    style={{ fontSize: '12px', padding: '4px 12px', borderRadius: '6px', border: '1px solid #d1d5db', background: '#fff', color: '#374151', cursor: 'pointer' }}
                  >
                    No, skip
                  </button>
                </div>
              )}
            </div>
          );
        }

        // ── New tender ────────────────────────────────────────────────────────
        return (
          <div key={i} style={{
            marginBottom: '10px', padding: '10px 12px', borderRadius: '8px',
            border: '1px solid #a7f3d0', background: '#f0fdf4',
          }}>
            <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '4px', color: '#065f46' }}>
              ✅ New tender created
            </div>
            <div style={{ fontSize: '13px', fontWeight: 500, marginBottom: '4px' }}>{r.title}</div>
            {r.tenderNo && (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Ref: {r.tenderNo}
              </div>
            )}
          </div>
        );
      })}
      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px' }}>
        Full details available in each tender's Details page.
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function ChatbotPanel({ isOpen, onClose, tenderId = null, onUploadComplete }) {
  const [messages, setMessages] = useState([
    {
      id: 1,
      text: "Hello! I'm your AI assistant. You can ask me questions about your tenders or upload a PDF document for structured data extraction.",
      sender: 'bot',
      type: 'text',
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);
  const [inputText,    setInputText]    = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  // { [msgId]: { [resultIndex]: 'pending'|'loading'|'confirmed'|'rejected'|'error' } }
  const [confirmStates, setConfirmStates] = useState({});
  const fileInputRef   = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isProcessing]);

  const addMessage = (payload, sender) => {
    setMessages(prev => [...prev, {
      id: crypto.randomUUID(),
      sender,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      ...(typeof payload === 'string'
        ? { text: payload, type: 'text' }
        : payload),
    }]);
  };

  // ── Duplicate-update confirmation handlers ───────────────────────────────────
  const handleConfirmUpdate = async (msgId, resultIdx, resultTenderId, patch, changedFields) => {
    setConfirmStates(prev => ({ ...prev, [msgId]: { ...(prev[msgId] || {}), [resultIdx]: 'loading' } }));
    try {
      await applyTenderUpdate(resultTenderId, patch, changedFields);
      setConfirmStates(prev => ({ ...prev, [msgId]: { ...(prev[msgId] || {}), [resultIdx]: 'confirmed' } }));
      if (onUploadComplete) onUploadComplete();
    } catch (err) {
      setConfirmStates(prev => ({ ...prev, [msgId]: { ...(prev[msgId] || {}), [resultIdx]: 'error' } }));
      addMessage(`⚠️ Failed to apply update: ${err.message}`, 'bot');
    }
  };

  const handleRejectUpdate = (msgId, resultIdx) => {
    setConfirmStates(prev => ({ ...prev, [msgId]: { ...(prev[msgId] || {}), [resultIdx]: 'rejected' } }));
  };

  // ── Text chat ────────────────────────────────────────────────────────────────
  const handleSendText = async () => {
    if (!inputText.trim()) return;
    const userQuery = inputText;
    addMessage(userQuery, 'user');
    setInputText('');
    setIsProcessing(true);
    try {
      const reply = await sendChatMessage(userQuery, tenderId);
      addMessage(reply, 'bot');
    } catch (err) {
      addMessage(`⚠️ Could not reach AI service: ${err.message}`, 'bot');
    } finally {
      setIsProcessing(false);
    }
  };

  // ── File upload ──────────────────────────────────────────────────────────────
  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    addMessage(`📎 Uploading **${file.name}** for AI extraction…`, 'user');
    setIsProcessing(true);
    try {
      const raw = await uploadFileForProcessing(file, tenderId);
      // raw is a JSON string from CAP action → parse it
      const result = typeof raw === 'string' ? JSON.parse(raw) : raw;
      addMessage({
        type: 'file-result',
        filename: file.name,
        results: result.results || [],
        message: result.message || '',
      }, 'bot');
      // Refresh dashboard if any tenders were created/updated
      if (result.results && result.results.length > 0 && onUploadComplete) {
        onUploadComplete();
      }
    } catch (err) {
      addMessage(`⚠️ File upload failed: ${err.message}`, 'bot');
    } finally {
      setIsProcessing(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // ── Render a single message bubble ──────────────────────────────────────────
  const renderMessage = (msg) => {
    if (msg.type === 'file-result') {
      return (
        <FileResultMessage
          filename={msg.filename}
          results={msg.results}
          message={msg.message}
          confirmStates={confirmStates[msg.id] || {}}
          onConfirm={(idx, resultTenderId, patch, changedFields) =>
            handleConfirmUpdate(msg.id, idx, resultTenderId, patch, changedFields)}
          onReject={(idx) => handleRejectUpdate(msg.id, idx)}
        />
      );
    }
    return <MarkdownText text={msg.text} />;
  };

  return (
    <>
      <div className={`chatbot-drawer ${isOpen ? 'open' : ''}`}>
        <div className="chatbot-header">
          <h3>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
            </svg>
            Copilot
            {tenderId && <span style={{ fontSize: '12px', opacity: 0.7, marginLeft: '8px' }}>• {tenderId}</span>}
          </h3>
          <button onClick={onClose} className="btn btn-ghost" style={{ padding: '4px 8px' }}>✕</button>
        </div>

        <div className="chatbot-messages">
          {messages.map(msg => (
            <div key={msg.id} className={`chat-msg ${msg.sender}`}>
              {renderMessage(msg)}
              <div className="chat-msg-time">{msg.time}</div>
            </div>
          ))}
          {isProcessing && (
            <div className="chat-msg bot">
              <div style={{ display: 'flex', gap: '4px', alignItems: 'center', padding: '4px 0' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor', animation: 'pulse 1s infinite' }} />
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor', animation: 'pulse 1s infinite 0.2s' }} />
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'currentColor', animation: 'pulse 1s infinite 0.4s' }} />
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="chatbot-input-area">
          <div className="chat-form">
            <input
              type="file"
              ref={fileInputRef}
              style={{ display: 'none' }}
              onChange={handleFileUpload}
              accept=".pdf"
            />
            <button
              className="chat-file-btn"
              onClick={() => fileInputRef.current?.click()}
              title="Upload PDF for extraction"
              disabled={isProcessing}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
              </svg>
            </button>
            <input
              type="text"
              className="chat-input"
              placeholder="Ask a question…"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !isProcessing && handleSendText()}
              disabled={isProcessing}
            />
            <button
              className="btn btn-primary"
              onClick={handleSendText}
              style={{ padding: '10px 16px' }}
              disabled={isProcessing}
            >
              Send
            </button>
          </div>
        </div>
      </div>
      <div className="drawer-overlay" onClick={onClose} />
    </>
  );
}
