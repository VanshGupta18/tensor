import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { streamChatMessage, uploadFileForProcessing, applyTenderUpdate } from '../api/chatApi.js';
import { validatePdfFile } from '../utils/fileUtils.js';

// ── PDF processing timeline ───────────────────────────────────────────────────
const UPLOAD_STAGES = [
  { label: 'Reading PDF', detail: 'Loading file into memory', delay: 0 },
  { label: 'Extracting text', detail: 'Parsing document structure', delay: 2800 },
  { label: 'Identifying tender fields', detail: 'Matching headers and metadata', delay: 6500 },
  { label: 'Running AI analysis', detail: 'Classifying and structuring fields', delay: 13000 },
  { label: 'Saving to database', detail: 'Persisting extracted tender data', delay: 24000 },
];

function UploadTimeline({ filename, isComplete }) {
  const [step, setStep] = useState(0);
  const [timestamps, setTimestamps] = useState([]);
  const timersRef = useRef([]);

  useEffect(() => {
    setTimestamps([new Date()]);
    timersRef.current = UPLOAD_STAGES.slice(1).map((s, i) =>
      setTimeout(() => {
        setStep(i + 1);
        setTimestamps(prev => {
          const newTs = [...prev];
          newTs[i + 1] = new Date();
          return newTs;
        });
      }, s.delay)
    );
    return () => timersRef.current.forEach(clearTimeout);
  }, []);

  useEffect(() => {
    if (isComplete) {
      timersRef.current.forEach(clearTimeout);
      setStep(UPLOAD_STAGES.length);
    }
  }, [isComplete]);

  return (
    <div style={{ fontSize: '13px', minWidth: '220px' }}>
      {/* Filename header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '7px', marginBottom: '16px' }}>
        <div style={{
          width: 28, height: 28, borderRadius: '6px', flexShrink: 0,
          background: 'color-mix(in srgb, var(--copper) 12%, transparent)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--copper)" strokeWidth="2" aria-hidden="true">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
        </div>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--ink)', lineHeight: 1.2 }}>{filename}</div>
          <div style={{ fontSize: '11px', color: 'var(--slate)', marginTop: '1px' }}>Processing…</div>
        </div>
      </div>

      {/* Stages */}
      {UPLOAD_STAGES.map((s, i) => {
        const done = i < step;
        const active = i === step;
        const isLast = i === UPLOAD_STAGES.length - 1;

        return (
          <div key={i} style={{ display: 'flex', gap: '12px', alignItems: 'stretch', paddingBottom: isLast ? '0' : '18px' }}>
            {/* Track column */}
            <div style={{ position: 'relative', width: '18px', flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              {/* Dot */}
              <div style={{
                width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: done ? 'var(--copper)' : 'transparent',
                border: done ? 'none' : '2px solid var(--copper)',
                borderColor: done ? 'transparent' : active ? 'var(--copper)' : 'var(--edge)',
                borderTopColor: active ? 'transparent' : '',
                boxSizing: 'border-box',
                animation: active ? 'spin 1.1s linear infinite' : 'none',
                transition: 'background 0.25s, border-color 0.25s',
                position: 'relative',
                zIndex: 2,
                marginTop: '1px',
              }}>
                {done && (
                  <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                )}
                {active && (
                  <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--copper)' }} />
                )}
              </div>

              {/* Connector */}
              {!isLast && (
                <div style={{
                  position: 'absolute',
                  top: '19px',
                  bottom: '-1px',
                  left: '8px',
                  width: 2,
                  background: done ? 'var(--copper)' : 'var(--edge-lt)',
                  transition: 'background 0.4s',
                  zIndex: 1,
                }} />
              )}
            </div>

            {/* Label column */}
            <div style={{
              flex: 1,
              paddingBottom: isLast ? '0' : '4px',
              opacity: i > step ? 0.38 : 1,
              transition: 'opacity 0.3s',
            }}>
              <div style={{
                fontWeight: active ? 600 : done ? 500 : 400,
                color: active ? 'var(--copper)' : done ? 'var(--ink)' : 'var(--slate)',
                lineHeight: 1.2, marginBottom: '2px',
                transition: 'color 0.25s',
              }}>
                {s.label}
              </div>
              <div style={{
                fontSize: '11px',
                color: active ? 'color-mix(in srgb, var(--copper) 70%, transparent)' : 'var(--slate)',
                transition: 'color 0.25s',
              }}>
                {s.detail}
              </div>
            </div>

            {/* Time column */}
            <div style={{
              fontSize: '10px',
              color: 'var(--slate)',
              opacity: done ? 0.6 : 0,
              transition: 'opacity 0.3s',
              paddingTop: '2px',
              whiteSpace: 'nowrap',
              fontVariantNumeric: 'tabular-nums',
            }}>
              {timestamps[i] ? timestamps[i].toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' }) : ''}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Simplified file-result card ───────────────────────────────────────────────
function FileResult({ filename, results, message, confirmStates, onConfirm, onReject }) {
  if (!results || results.length === 0) {
    return (
      <div style={{ fontSize: '13px' }}>
        <span style={{ fontWeight: 600 }}>📄 {filename}</span>
        <div style={{ color: 'var(--text-muted)', marginTop: '4px' }}>
          {message || 'No tender information found.'}
        </div>
      </div>
    );
  }

  return (
    <div style={{ fontSize: '13px' }}>
      <div style={{ fontWeight: 600, marginBottom: '8px' }}>📄 {filename}</div>
      {results.map((r, i) => {
        const state = confirmStates?.[i];

        if (r.requiresConfirmation && r.changedFields?.length > 0) {
          return (
            <div key={i} style={{
              padding: '10px 12px', borderRadius: '8px',
              border: '1px solid #fbbf24', background: '#fffbeb', marginBottom: '8px',
            }}>
              <div style={{ fontWeight: 600, color: '#92400e', marginBottom: '4px' }}>
                ⚠️ Duplicate — {r.tenderNo || r.title}
              </div>
              <div style={{ color: '#78350f', marginBottom: '8px', fontSize: '12px' }}>
                Update existing tender with info from this PDF?
              </div>
              {state === 'confirmed' && <div style={{ color: '#065f46', fontWeight: 500 }}>✅ Updated.</div>}
              {state === 'rejected' && <div style={{ color: 'var(--text-muted)' }}>Skipped.</div>}
              {state === 'error' && <div style={{ color: '#dc2626' }}>Update failed.</div>}
              {(!state || state === 'loading') && (
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    onClick={() => onConfirm(i, r.tenderId, r.pendingPatch, r.changedFields)}
                    disabled={state === 'loading'}
                    style={{ padding: '4px 14px', borderRadius: '6px', border: 'none', background: '#059669', color: '#fff', cursor: 'pointer', fontWeight: 600, fontSize: '12px' }}
                  >
                    {state === 'loading' ? 'Updating…' : 'Yes, update'}
                  </button>
                  <button
                    onClick={() => onReject(i)}
                    disabled={state === 'loading'}
                    style={{ padding: '4px 14px', borderRadius: '6px', border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer', fontSize: '12px' }}
                  >
                    Skip
                  </button>
                </div>
              )}
            </div>
          );
        }

        return (
          <div key={i} style={{
            padding: '10px 12px', borderRadius: '8px',
            border: '1px solid #a7f3d0', background: '#f0fdf4', marginBottom: '8px',
          }}>
            <div style={{ fontWeight: 600, color: '#065f46' }}>
              ✅ {r.requiresConfirmation ? 'No changes found' : 'Tender saved'}
            </div>
            <div style={{ color: 'var(--text-muted)', marginTop: '2px' }}>{r.title}</div>
            {r.tenderNo && <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{r.tenderNo}</div>}
          </div>
        );
      })}
    </div>
  );
}

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

    addMessage(`Uploading **${file.name}**…`, 'user');
    setUploadFilename(file.name);
    setIsProcessing(true);
    setIsUploadComplete(false);
    setProcessingType('upload');

    try {
      const raw = await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Timed out after 10 minutes.')), 600_000);
        uploadFileForProcessing(file, tenderId)
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
                <UploadTimeline filename={uploadFilename} isComplete={isUploadComplete} />
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
