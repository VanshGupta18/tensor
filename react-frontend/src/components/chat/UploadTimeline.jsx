import React, { useState, useEffect, useRef } from 'react';

function truncateFilename(name, max = 36) {
  if (!name || name.length <= max) return name;
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.')) : '';
  const base = name.slice(0, name.length - ext.length);
  const keep = max - ext.length - 1;
  return `${base.slice(0, Math.max(8, keep))}…${ext}`;
}

/** Tick elapsed seconds locally — don't wait for poll intervals. */
function useElapsedClock() {
  const startedAt = useRef(Date.now());
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const tick = () => setSeconds(Math.floor((Date.now() - startedAt.current) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return seconds;
}

/**
 * Animate displayed % toward server target; creep slowly between polls so the
 * bar never sits frozen, and ease to 100 on completion.
 */
function useSmoothPercent(serverPercent, isComplete) {
  const [display, setDisplay] = useState(0);
  const targetRef = useRef(0);

  useEffect(() => {
    if (isComplete) {
      targetRef.current = 100;
      return;
    }
    const next = Math.max(0, serverPercent ?? 0);
    // Server is source of truth — never regress
    if (next > targetRef.current) targetRef.current = next;
  }, [serverPercent, isComplete]);

  useEffect(() => {
    let raf;
    const animate = () => {
      setDisplay(prev => {
        const target = isComplete ? 100 : targetRef.current;

        if (isComplete) {
          const step = (100 - prev) * 0.14;
          return step < 0.4 ? 100 : prev + step;
        }

        if (prev < target) {
          const step = (target - prev) * 0.07;
          return step < 0.15 ? target : prev + step;
        }

        // Between server updates, creep toward next milestone (cap 97 until done)
        if (prev < 97) return prev + 0.025;
        return prev;
      });
      raf = requestAnimationFrame(animate);
    };
    raf = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(raf);
  }, [isComplete]);

  return display;
}

export default function UploadTimeline({ filename, progress, isComplete }) {
  const p = progress || {};
  const serverPercent = isComplete ? 100 : (p.percent ?? 0);
  const displayPercent = useSmoothPercent(serverPercent, isComplete);
  const localElapsed = useElapsedClock();
  const elapsed = Math.max(localElapsed, p.elapsedSec || 0);

  const groupsDone = p.groupsDone || 0;
  const groupsTotal = p.groupsTotal || 6;
  const pctLabel = Math.min(100, Math.round(displayPercent));

  const statusLine = isComplete
    ? 'Extraction complete'
    : (p.detail || 'Processing document…');

  const sectionHint = !isComplete && groupsDone > 0
    ? `${groupsDone}/${groupsTotal} sections`
    : null;

  return (
    <div className="upload-progress">
      <div className="upload-progress__row">
        <div className="upload-progress__icon" aria-hidden="true">
          {isComplete ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
          )}
        </div>

        <div className="upload-progress__body">
          <div className="upload-progress__filename" title={filename}>
            {truncateFilename(filename)}
          </div>
          <div className="upload-progress__status">
            {statusLine}
            <span className="upload-progress__elapsed"> · {elapsed}s</span>
            {sectionHint && (
              <span className="upload-progress__sections"> · {sectionHint}</span>
            )}
          </div>
        </div>

        <div className={`upload-progress__pct${isComplete ? ' upload-progress__pct--done' : ''}`}>
          {pctLabel}%
        </div>
      </div>

      <div
        className="upload-progress__bar-track"
        role="progressbar"
        aria-valuenow={pctLabel}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={statusLine}
      >
        <div
          className={`upload-progress__bar-fill${isComplete ? ' upload-progress__bar-fill--done' : ''}`}
          style={{ width: `${displayPercent}%` }}
        />
      </div>
    </div>
  );
}
