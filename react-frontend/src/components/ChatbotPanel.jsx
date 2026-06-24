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
function FileResultMessage({ filename, results, message, confirmStates, onConfirm, onReject, onViewChanges }) {
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

        if (r.requiresConfirmation) {
          if (!r.changedFields || r.changedFields.length === 0) {
            return (
              <div key={i} style={{
                marginBottom: '10px', padding: '10px 12px', borderRadius: '8px',
                border: '1px solid var(--border-color)', background: 'var(--bg-hover)',
              }}>
                <div style={{ fontWeight: 600, fontSize: '13px', marginBottom: '4px', color: 'var(--text-muted)' }}>
                  ℹ️ No changes found in followup
                </div>
                <div style={{ fontSize: '13px', fontWeight: 500, marginBottom: '4px' }}>{r.title}</div>
                {r.tenderNo && (
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    Ref: {r.tenderNo}
                  </div>
                )}
              </div>
            );
          }

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

              {r.changedFields && r.changedFields.length > 0 && (
                <div style={{ marginBottom: '10px' }}>
                  <button
                    type="button"
                    onClick={() => onViewChanges(r)}
                    style={{
                      fontSize: '12px',
                      color: 'var(--primary)',
                      background: 'none',
                      border: 'none',
                      textDecoration: 'underline',
                      cursor: 'pointer',
                      padding: 0,
                      fontWeight: 600,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '4px'
                    }}
                  >
                    🔍 SEE followup changes
                  </button>
                </div>
              )}

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
export default function ChatbotPanel({ isOpen, onClose, tenderId = null, onUploadComplete, mode = 'normal', setMode, tenders = [] }) {
  const [messages, setMessages] = useState([
    {
      id: 1,
      text: "Hello! I'm your AI assistant. You can ask me questions about your tenders or upload a PDF document for structured data extraction.",
      sender: 'bot',
      type: 'text',
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }
  ]);
  const [inputText, setInputText] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  // { [msgId]: { [resultIndex]: 'pending'|'loading'|'confirmed'|'rejected'|'error' } }
  const [confirmStates, setConfirmStates] = useState({});
  const [viewingChanges, setViewingChanges] = useState(null);
  const [activeTab, setActiveTab] = useState('table'); // 'table' | 'json'
  const fileInputRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isProcessing]);

  useEffect(() => {
    if (isOpen && mode === 'followup' && tenderId) {
      setMessages(prev => {
        // Prevent duplicate follow-up prompts for the same session/opening
        const hasFollowUpPrompt = prev.some(m => m.isFollowUpPrompt && m.tenderId === tenderId);
        if (hasFollowUpPrompt) return prev;

        return [...prev, {
          id: `followup-${Date.now()}`,
          isFollowUpPrompt: true,
          tenderId,
          text: `Add a follow-up file for tender context **${tenderId}**:`,
          sender: 'bot',
          type: 'followup-request',
          time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        }];
      });
      if (setMode) setMode('normal');
    }
  }, [isOpen, mode, tenderId, setMode]);

  const addMessage = (payload, sender) => {
    setMessages(prev => [...prev, {
      id: Date.now(),
      sender,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      ...(typeof payload === 'string'
        ? { text: payload, type: 'text' }
        : payload),
    }]);
  };

  // ── Duplicate-update confirmation handlers ───────────────────────────────────
  const handleConfirmUpdate = async (msgId, resultIdx, tenderId, patch, changedFields) => {
    setConfirmStates(prev => ({ ...prev, [msgId]: { ...(prev[msgId] || {}), [resultIdx]: 'loading' } }));
    try {
      await applyTenderUpdate(tenderId, patch, changedFields);
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
          onConfirm={(idx, tenderId, patch, changedFields) =>
            handleConfirmUpdate(msg.id, idx, tenderId, patch, changedFields)}
          onReject={(idx) => handleRejectUpdate(msg.id, idx)}
          onViewChanges={(r) => setViewingChanges(r)}
        />
      );
    }
    if (msg.type === 'followup-request') {
      return (
        <div>
          <MarkdownText text={msg.text} />
          <div style={{ marginTop: '10px' }}>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="btn btn-primary btn-sm"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
              Upload Follow-up File
            </button>
          </div>
        </div>
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

      {viewingChanges && (() => {
        const existingTender = tenders?.find(t => t.id === viewingChanges.tenderId);
        return (
          <div className="modal-overlay" style={{ zIndex: 110 }}>
            <div className="modal-content" style={{ maxWidth: '650px', width: '95vw' }}>
              <div className="modal-header">
                <h3>Follow-up Changes — {viewingChanges.tenderNo || viewingChanges.tenderId}</h3>
                <button onClick={() => setViewingChanges(null)} className="btn btn-ghost" style={{ padding: '4px 8px' }}>✕</button>
              </div>
              <div className="modal-body" style={{ padding: '20px', minHeight: '320px', display: 'flex', flexDirection: 'column' }}>
                {/* Tab Navigation */}
                <div style={{ display: 'flex', borderBottom: '1px solid var(--border-color)', marginBottom: '16px' }}>
                  <button
                    type="button"
                    onClick={() => setActiveTab('table')}
                    style={{
                      padding: '8px 16px',
                      border: 'none',
                      background: 'none',
                      borderBottom: activeTab === 'table' ? '2px solid var(--primary)' : 'none',
                      color: activeTab === 'table' ? 'var(--primary)' : 'var(--text-muted)',
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontSize: '13px',
                    }}
                  >
                    📋 Database Table (Tenders)
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab('json')}
                    style={{
                      padding: '8px 16px',
                      border: 'none',
                      background: 'none',
                      borderBottom: activeTab === 'json' ? '2px solid var(--primary)' : 'none',
                      color: activeTab === 'json' ? 'var(--primary)' : 'var(--text-muted)',
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontSize: '13px',
                    }}
                  >
                    {"{ }"} Whole JSON File
                  </button>
                </div>

                {activeTab === 'table' && (
                  <div style={{ flex: 1 }}>
                    <p style={{ margin: '0 0 12px 0', fontSize: '13px', color: 'var(--text-muted)' }}>
                      Comparing current database values against the follow-up PDF values:
                    </p>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                      <thead>
                        <tr style={{ borderBottom: '2px solid var(--border-color)', textAlign: 'left', backgroundColor: 'var(--bg-page)' }}>
                          <th style={{ padding: '10px 8px', fontWeight: 600 }}>Field Column</th>
                          <th style={{ padding: '10px 8px', fontWeight: 600 }}>Current DB Value</th>
                          <th style={{ padding: '10px 8px', fontWeight: 600 }}>Extracted PDF Value</th>
                          <th style={{ padding: '10px 8px', fontWeight: 600, textAlign: 'center' }}>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          { label: 'Tender No', dbVal: existingTender?.tenderNo, extVal: viewingChanges.extractedValues?.tenderNo },
                          { label: 'Title',     dbVal: existingTender?.title,    extVal: viewingChanges.extractedValues?.title },
                          { label: 'Budget',    dbVal: existingTender?.details?.budget,   extVal: viewingChanges.extractedValues?.budget },
                          { label: 'Deadline',  dbVal: existingTender?.details?.deadline, extVal: viewingChanges.extractedValues?.deadline },
                          { label: 'Location',  dbVal: existingTender?.details?.location, extVal: viewingChanges.extractedValues?.location },
                        ].map((item, idx) => {
                          const dbStr = (item.dbVal === null || item.dbVal === undefined) ? '' : String(item.dbVal).trim();
                          const extStr = (item.extVal === null || item.extVal === undefined) ? '' : String(item.extVal).trim();
                          const isChanged = dbStr !== extStr;

                          return (
                            <tr key={idx} style={{ borderBottom: '1px solid var(--border-color)', backgroundColor: isChanged ? 'rgba(251, 191, 36, 0.05)' : 'transparent' }}>
                              <td style={{ padding: '10px 8px', fontWeight: 600 }}>{item.label}</td>
                              <td style={{ padding: '10px 8px', color: 'var(--text-main)', wordBreak: 'break-word' }}>{item.dbVal || '—'}</td>
                              <td style={{ padding: '10px 8px', color: isChanged ? 'var(--success)' : 'var(--text-main)', fontWeight: isChanged ? 600 : 400, wordBreak: 'break-word' }}>{item.extVal || '—'}</td>
                              <td style={{ padding: '10px 8px', textAlign: 'center' }}>
                                {isChanged ? (
                                  <span style={{
                                    display: 'inline-block', padding: '2px 8px', borderRadius: '4px',
                                    fontSize: '11px', fontWeight: 600, background: '#fef3c7', color: '#b45309', border: '1px solid #fcd34d'
                                  }}>
                                    Modified
                                  </span>
                                ) : (
                                  <span style={{
                                    display: 'inline-block', padding: '2px 8px', borderRadius: '4px',
                                    fontSize: '11px', fontWeight: 500, background: '#f3f4f6', color: '#6b7280', border: '1px solid #e5e7eb'
                                  }}>
                                    Unchanged
                                  </span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}

                {activeTab === 'json' && (
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
                    <p style={{ margin: '0 0 12px 0', fontSize: '13px', color: 'var(--text-muted)' }}>
                      Complete raw JSON payload extracted from the follow-up file by the Python AI Service:
                    </p>
                    <pre style={{
                      backgroundColor: '#1e1e1e',
                      color: '#d4d4d4',
                      padding: '16px',
                      borderRadius: '8px',
                      overflow: 'auto',
                      maxHeight: '320px',
                      fontSize: '12px',
                      fontFamily: 'Consolas, Monaco, monospace',
                      textAlign: 'left',
                      margin: 0,
                      flex: 1
                    }}>
                      {JSON.stringify(viewingChanges.rawJson, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
              <div className="modal-footer" style={{ padding: '12px 20px' }}>
                <button onClick={() => setViewingChanges(null)} className="btn btn-primary">
                  Close
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </>
  );
}
