# mbsrn Operator UI

Standalone Next.js operator surface for mbsrn.

## Local development

```bash
npm ci
npm run dev
```

Set environment values in `.env.local`:

- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID`

## Production standalone build note

This app uses Next.js `output: "standalone"`.

- `sharp` must remain installed in `dependencies` (not `devDependencies`) for image optimization in standalone runtime mode.
- The standalone build output (`.next/standalone`) includes traced runtime `node_modules` used by `server.js`; runtime images should copy that output directly.
- Branding and other static assets live under `frontend/operator-ui/public/` and are referenced by root-relative URLs (for example `/images/mbsrn-logo.jpg`).
- Standalone runtime images must copy both `.next/static` and `public/`; otherwise static image URLs can return HTML fallback responses instead of `image/*`.

Authentication flow:

1. UI collects Google ID token (Google Identity Services button or manual token input).
2. UI exchanges token with backend `POST /api/auth/google/exchange`.
3. Backend returns app access/refresh tokens bound to internal principal/business.
4. UI stores:
   - access token in `sessionStorage`
   - refresh token in memory only for the active browser session
5. UI uses bearer access token for business-scoped API calls.
6. Sign out calls `POST /api/auth/logout` and clears local session state.
