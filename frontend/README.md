# Frontend Apps

`frontend/operator-ui` contains the standalone operator application (Next.js + TypeScript).

Current implemented operator pages:
1. Dashboard
2. Sites
3. Audit runs
4. Competitor intelligence sets
5. Recommendations
6. Automation run history

Local run:

```bash
cd frontend/operator-ui
npm install
npm run dev
```

Set `frontend/operator-ui/.env.local` with:
- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID`
