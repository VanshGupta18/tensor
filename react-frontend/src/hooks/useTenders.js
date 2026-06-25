import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getTenders,
  updateTender,
  markReviewed,
  submitAuditBatch,
} from '../api/tenderApi.js';

export function useTenders(username) {
  const queryClient = useQueryClient();

  // ── List query ──────────────────────────────────────────────────────────────
  const { data: tenders = [], isLoading: loading, error: queryError } = useQuery({
    queryKey: ['tenders'],
    queryFn: getTenders,
    enabled: !!username,  // don't fetch before login
  });

  // ── markReviewed mutation ───────────────────────────────────────────────────
  const markReviewedMutation = useMutation({
    mutationFn: ({ id }) => markReviewed(id, username),
    onMutate: async ({ id }) => {
      await queryClient.cancelQueries({ queryKey: ['tenders'] });
      const prev = queryClient.getQueryData(['tenders']) || [];
      // Optimistic: stamp the reviewer immediately
      queryClient.setQueryData(['tenders'],
        prev.map(t => t.id === id ? { ...t, lastReviewedBy: username } : t)
      );
      return { prev };
    },
    onError: (_, __, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['tenders'], ctx.prev);
    },
    onSuccess: (_, { id }) => {
      // Optimistic update already stamped lastReviewedBy — sync to detail cache
      const updated = queryClient.getQueryData(['tenders'])?.find(t => t.id === id);
      if (updated) queryClient.setQueryData(['tender', id], updated);
    },
  });

  // ── saveChanges mutation ────────────────────────────────────────────────────
  const saveChangesMutation = useMutation({
    mutationFn: ({ tenderId, updatedFormValues }) =>
      updateTender(tenderId, updatedFormValues, username),
    onMutate: async ({ tenderId, updatedFormValues }) => {
      await queryClient.cancelQueries({ queryKey: ['tenders'] });
      const prev = queryClient.getQueryData(['tenders']) || [];
      queryClient.setQueryData(['tenders'], old =>
        (old || []).map(t =>
          t.id === tenderId
            ? {
                ...t,
                title: updatedFormValues.title,
                details: {
                  budget:     updatedFormValues.budget,
                  deadline:   updatedFormValues.deadline,
                  status:     updatedFormValues.status,
                  location:   updatedFormValues.location,
                  contractor: updatedFormValues.contractor,
                },
              }
            : t
        )
      );
      return { prev };
    },
    onError: (_, __, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['tenders'], ctx.prev);
    },
    onSuccess: (_, { tenderId, updatedFormValues }) => {
      queryClient.setQueryData(['tenders'], old =>
        (old || []).map(t => t.id === tenderId
          ? {
              ...t,
              title:         updatedFormValues.title,
              lastChangedBy: username,
              details: {
                budget:     updatedFormValues.budget,
                deadline:   updatedFormValues.deadline,
                status:     updatedFormValues.status,
                location:   updatedFormValues.location,
                contractor: updatedFormValues.contractor,
              },
            }
          : t
        )
      );
      const updated = queryClient.getQueryData(['tenders'])?.find(t => t.id === tenderId);
      if (updated) queryClient.setQueryData(['tender', tenderId], updated);
    },
  });

  // ── Public API (same interface as before) ───────────────────────────────────

  const handleMarkReviewed = async (tender) => {
    await markReviewedMutation.mutateAsync({ id: tender.id });
    return (
      queryClient.getQueryData(['tenders'])?.find(t => t.id === tender.id)
      ?? { ...tender, lastReviewedBy: username }
    );
  };

  const handleSaveChanges = async (tenderId, updatedFormValues, changedList, remarksObject) => {
    await saveChangesMutation.mutateAsync({ tenderId, updatedFormValues });
    if (changedList.length > 0) {
      try {
        await submitAuditBatch(tenderId, changedList, remarksObject, username);
      } catch (auditErr) {
        console.error('Audit batch failed after successful save:', auditErr);
      }
    }
  };

  return {
    tenders,
    loading,
    error: queryError?.message || null,
    handleMarkReviewed,
    handleSaveChanges,
  };
}
