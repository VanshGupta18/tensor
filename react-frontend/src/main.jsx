import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,   // 5 min — halves background refetch frequency
      gcTime:    10 * 60 * 1000,  // 10 min — keep in memory after unmount
      retry: 1,
    },
  },
})

// ── sessionStorage persistence for tenders list (zero extra packages) ──────────
const CACHE_KEY = 'tq-tenders';
const CACHE_TTL = 10 * 60 * 1000;

try {
  const raw = sessionStorage.getItem(CACHE_KEY);
  if (raw) {
    const { data, ts } = JSON.parse(raw);
    if (Date.now() - ts < CACHE_TTL) {
      queryClient.setQueryData(['tenders'], data);
    } else {
      sessionStorage.removeItem(CACHE_KEY);
    }
  }
} catch {}

queryClient.getQueryCache().subscribe(event => {
  if (
    event.type === 'updated' &&
    event.query.queryKey[0] === 'tenders' &&
    event.query.state.status === 'success'
  ) {
    try {
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({
        data: event.query.state.data,
        ts: Date.now(),
      }));
    } catch {}
  }
});

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
)
