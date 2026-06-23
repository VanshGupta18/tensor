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
import { INITIAL_TENDERS } from '../data.js';

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
      setTenders(INITIAL_TENDERS);   // show example data when backend is unavailable
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
    try {
      // 1. PATCH the tender
      const updated = await updateTender(tenderId, updatedFormValues, username);

      // 2. Post audit entries for each changed field
      if (changedList.length > 0) {
        await submitAuditBatch(tenderId, changedList, remarksObject, username);
      }

      // 3. Update local state
      setTenders(prev => prev.map(t => t.id === updated.id ? updated : t));
      return updated;
    } catch (err) {
      console.error('handleSaveChanges failed:', err);
      // Optimistic fallback
      const timestamp = new Date().toISOString().replace('T', ' ').substring(0, 16);
      setTenders(prev => prev.map(t => {
        if (t.id !== tenderId) return t;
        const newRemarks = [...t.remarks];
        changedList.forEach(change => {
          newRemarks.push({
            fieldName: change.field,
            oldVal:    change.oldVal,
            newVal:    change.newVal,
            remark:    remarksObject[change.field] || 'No remarks provided',
            changedBy: username,
            changedAt: timestamp,
          });
        });
        return {
          ...t,
          title:         updatedFormValues.title,
          lastChangedBy: username,
          details:       { ...t.details, ...updatedFormValues },
          remarks:       newRemarks,
        };
      }));
      throw err;
    }
  }, [username]);

  return { tenders, loading, error, refresh, handleMarkReviewed, handleSaveChanges };
}
