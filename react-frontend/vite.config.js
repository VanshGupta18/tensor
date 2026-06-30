import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // Output directly into CAP's app/ folder so `cds build` bundles it into gen/srv.
    outDir: '../cap-backend/app',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // ── /api  →  CAP (port 4004) ──────────────────────────────────────────────
      // All OData, auth, and stream-chat calls go through here.
      // Vite strips the /api prefix before forwarding (rewrite below).
      '/api': {
        target:      'http://localhost:4004',
        changeOrigin: true,
        rewrite:     (path) => path.replace(/^\/api/, ''),
      },

      // ── /upload  →  CAP (port 4004) ───────────────────────────────────────────
      // Multipart PDF upload. CAP base64-encodes the binary and forwards it to the
      // Python AI service, which can take several minutes on large documents.
      //
      // WHY configure() instead of top-level timeout/proxyTimeout:
      //   In Vite 8 (http-proxy-middleware v3) the top-level `timeout` key sets the
      //   TCP *connection* timeout, not the *socket idle* timeout. During AI processing
      //   the upstream sends nothing for minutes — the connection stays open but idle —
      //   so the socket idle timer fires and Vite closes the pipe with a 502.
      //   The only reliable fix is to extend the socket's own timeout via configure().
      '/upload': {
        target:       'http://localhost:4004',
        changeOrigin: true,

        configure(proxy) {
          // Extend socket idle timeout to 10 minutes on both legs of the proxy so
          // a long-running AI extraction doesn't get cut off mid-flight.
          proxy.on('proxyReq', (_proxyReq, req) => {
            req.socket.setTimeout(600_000);
          });
          proxy.on('proxyRes', (_proxyRes, _req, res) => {
            res.socket?.setTimeout(600_000);
          });

          // Convert proxy-level errors (ECONNREFUSED, socket hang-up, etc.) to JSON
          // so the browser receives a parseable error body instead of Vite's HTML 502
          // page, which our fetch handler can't parse and re-shows as a generic message.
          proxy.on('error', (err, _req, res) => {
            console.error('[vite proxy /upload]', err.code, err.message);
            if (res.headersSent) return;
            res.writeHead(502, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({
              error: err.code === 'ECONNREFUSED'
                ? 'CAP backend is not running on port 4004. Start it with: npm start (in cap-backend/)'
                : `Proxy error: ${err.message}`,
            }));
          });
        },
      },
    },
  },
})
