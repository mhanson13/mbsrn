# Work Boots Operator UI

Standalone Next.js operator surface for Work Boots Console.

## Local development

```bash
npm install
npm run dev
```

Set environment values in `.env.local`:

- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID`

Authentication flow:

1. UI collects Google ID token (Google Identity Services button or manual token input).
2. UI exchanges token with backend `POST /api/auth/google/exchange`.
3. Backend returns app access/refresh tokens bound to internal principal/business.
4. UI stores:
   - access token in `sessionStorage`
   - refresh token in memory only for the active browser session
5. UI uses bearer access token for business-scoped API calls.
6. Sign out calls `POST /api/auth/logout` and clears local session state.
