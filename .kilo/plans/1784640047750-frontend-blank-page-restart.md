# Frontend blank page + restart diagnosis

Confirmed cause: no active backend or frontend process is running right now. `localhost:3000` is blank because nothing healthy is serving the Next.js app.

## Manual restart
- Backend: `cd C:\Users\rodri\Desktop\nexus\nexus-ide && .venv\Scripts\python.exe -m uvicorn backend.orchestrator.main:app --reload --port 8000`
- Frontend: `cd C:\Users\rodri\Desktop\nexus\nexus-ide\frontend && npm run dev`

## Next checks if it stays blank
1. Open browser DevTools Network/Console.
2. If HTML loads but CSS/JS 404s, check Next webpack/build output.
3. If `/` returns 200 but body is empty, check server-side render errors in terminal.
4. If API calls immediately fail, the backend may be down or CORS/auth is blocking.
