import { useQuery } from '@tanstack/react-query';
import { getTenderDocuments } from '../api/tenderApi.js';

/**
 * Fetches all documents (with AI result) for a given tender.
 * Cached for 5 minutes — re-used when navigating back to the same tender.
 */
export function useTenderDocuments(tenderId) {
  return useQuery({
    queryKey: ['tender', tenderId, 'documents'],
    queryFn: () => getTenderDocuments(tenderId),
    enabled: !!tenderId,
    staleTime: 5 * 60 * 1000,
  });
}
