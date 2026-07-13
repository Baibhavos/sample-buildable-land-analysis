# Frontend — Buildable Land Analysis

Next.js 16 + React 19 + MapLibre GL map UI. It talks to the FastAPI backend.

```bash
npm install
npm run dev   # http://localhost:3000
```

Set `NEXT_PUBLIC_API_BASE` if the backend isn't at `http://127.0.0.1:8000`
(see `.env.local.example`).

Key files:

- `src/app/page.tsx` — loads the map app client-side (`ssr:false`).
- `src/components/BuildableApp.tsx` — map, draw tools, setback controls, results.
- `src/lib/api.ts` — typed backend client + shared color palette.

See the root [`README.md`](../README.md) and [`WRITEUP.md`](../WRITEUP.md) for
the full picture.
