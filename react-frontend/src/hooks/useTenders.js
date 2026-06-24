/**
 * hooks/useTenders.js
 *
 * Custom hook encapsulating all Tender data management.
 * Replaces the raw useState(INITIAL_TENDERS) in App.jsx.
 *
 * Usage:
 *   const { tenders, loading, error, refresh, handleSaveChanges, handleMarkReviewed } = useTenders(username);
 */

import { useState, useEffect, useCallback } from 'react';
import {
  getTenders,
  updateTender,
  markReviewed,
  submitAuditBatch,
} from '../api/tenderApi.js';

export function useTenders(username) {
  const [tenders,  setTenders]  = useState([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState(null);

  // ── Fetch all tenders ────────────────────────────────────────────────────────
  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getTenders();
      setTenders(data);
    } catch (err) {
      setError(err.message || 'Failed to load tenders');
      setTenders([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // ── Mark reviewed (called when clicking View/Edit in Dashboard) ───────────────
  const handleMarkReviewed = useCallback(async (tender) => {
    if (!username) return tender;
    try {
      const updated = await markReviewed(tender.id, username);
      setTenders(prev => prev.map(t => t.id === updated.id ? updated : t));
      return updated;
    } catch (err) {
      console.error('markReviewed failed:', err);
      // Optimistic fallback so UI doesn't break
      const optimistic = { ...tender, lastReviewedBy: username };
      setTenders(prev => prev.map(t => t.id === tender.id ? optimistic : t));
      return optimistic;
    }
  }, [username]);

  // ── Save changes + post audit entries ────────────────────────────────────────
  const handleSaveChanges = useCallback(async (tenderId, updatedFormValues, changedList, remarksObject) => {
    // 1. PATCH the tender — throws on failure so caller can display the error
    const updated = await updateTender(tenderId, updatedFormValues, username);

    // 2. Update local state immediately (PATCH succeeded)
    setTenders(prev => prev.map(t => t.id === updated.id ? updated : t));

    // 3. Post audit entries — best-effort; failure doesn't roll back the PATCH
    if (changedList.length > 0) {
      try {
        await submitAuditBatch(tenderId, changedList, remarksObject, username);
      } catch (auditErr) {
        console.error('Audit batch failed after successful save:', auditErr);
      }
    }

    return updated;
  }, [username]);

  return { tenders, loading, error, refresh, handleMarkReviewed, handleSaveChanges };
}
