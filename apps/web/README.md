# HireFlow Web

Next.js recruiter UI for HireFlow. See the [root README](../../README.md) for setup and deployment.

```bash
npm install
npm run dev -- -p 3001
```

The app proxies API calls to `/backend/*`, which forwards to the FastAPI service configured via `HIREFLOW_API_URL`.
