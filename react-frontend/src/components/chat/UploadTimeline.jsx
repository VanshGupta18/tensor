import React, { useState, useRef, useEffect } from 'react';

// ── PDF processing timeline ───────────────────────────────────────────────────
const UPLOAD_STAGES = [
  { label: 'Validating file', detail: 'Checking file size and hash', delay: 0 },
  { label: 'Reading PDF', detail: 'Loading file into memory', delay: 800 },
  { label: 'Extracting text', detail: 'Parsing document structure', delay: 2800 },
  { label: 'Identifying tender fields', detail: 'Matching headers and metadata', delay: 6500 },
  { label: 'Running AI analysis', detail: 'Classifying and structuring fields', delay: 13000 },
  { label: 'Saving to database', detail: 'Persisting extracted tender data', delay: 24000 },
];

export default function UploadTimeline({ filename, isComplete }) {
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
