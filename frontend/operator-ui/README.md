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
3. Backend returns app bearer token bound to internal principal/business.
4. UI uses bearer token for business-scoped API calls.
