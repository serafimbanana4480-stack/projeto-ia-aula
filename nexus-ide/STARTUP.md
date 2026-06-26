# NEXUS IDE Startup Guide

This document provides instructions for starting the NEXUS IDE frontend and backend servers.

## Prerequisites

- Python 3.12.10 installed
- Node.js and npm installed
- Redis (optional, for some features)
- Ollama (optional, for LLM features)

## Python Installation

**Python Location:**
```
C:\Users\rodri\AppData\Local\Programs\Python\Python312\python.exe
```

**Using Python (Full Path):**
```bash
C:\Users\rodri\AppData\Local\Programs\Python\Python312\python.exe --version
C:\Users\rodri\AppData\Local\Programs\Python\Python312\python.exe -m pip --version
```

**Adding Python to PATH (Optional):**
1. Search for "Environment Variables" in Windows
2. Click "Edit the system environment variables"
3. Click "Environment Variables"
4. Under "System variables", find "Path" and click "Edit"
5. Click "New" and add: `C:\Users\rodri\AppData\Local\Programs\Python\Python312\`
6. Click "New" and add: `C:\Users\rodri\AppData\Local\Programs\Python\Python312\Scripts\`
7. Click OK on all dialogs
8. Restart your terminal

After adding to PATH, you can use:
```bash
python --version
pip --version
```

## Directory Structure

```
nexus-ide/
├── frontend/          # Next.js frontend application
│   ├── package.json
│   ├── node_modules/
│   └── app/
├── backend/           # FastAPI backend application
│   ├── orchestrator/
│   │   └── main.py    # Backend entry point
│   └── requirements.txt
└── .env               # Environment variables (create from .env.example)
```

## Environment Setup

1. **Create .env file:**
```bash
cd nexus-ide
copy .env.example .env
```

2. **Environment Variables (.env):**
```
OLLAMA_HOST=http://localhost:11434
OLLAMA_DASHBOARD_HOST=http://localhost:11435
REDIS_URL=redis://localhost:6379
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
LOG_LEVEL=INFO
NEXT_PUBLIC_API_URL=http://localhost:8000
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
PROMETHEUS_PORT=9090
```

## Dependency Installation

### Frontend Dependencies
```bash
cd nexus-ide/frontend
npm install
```

Verify installation:
```bash
npm list --depth=0
```

### Backend Dependencies

**Option A: Using Virtual Environment (Recommended)**
```bash
cd nexus-ide
C:\Users\rodri\AppData\Local\Programs\Python\Python312\python.exe -m venv venv
venv\Scripts\activate
pip install -r backend/requirements.txt
```

**Option B: Using System Python**
```bash
cd nexus-ide
C:\Users\rodri\AppData\Local\Programs\Python\Python312\python.exe -m pip install -r backend/requirements.txt
```

Verify installation:
```bash
pip list
```

## Starting the Servers

### Start Backend (Terminal 1)
```bash
cd nexus-ide

# If using venv:
venv\Scripts\activate
python -m backend.orchestrator.main

# If using system Python:
C:\Users\rodri\AppData\Local\Programs\Python\Python312\python.exe -m backend.orchestrator.main
```

Backend will start on: http://localhost:8000

### Start Frontend (Terminal 2)
```bash
cd nexus-ide/frontend
npm run dev
```

Frontend will start on: http://localhost:3000

## CORS Configuration

The backend is configured to allow CORS from:
- http://localhost:3000
- http://127.0.0.1:3000

This is configured in `backend/orchestrator/main.py`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Connectivity Test

After starting the backend, test connectivity:
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "ok"}
```

## Troubleshooting

**Python not found:**
- Use full path: `C:\Users\rodri\AppData\Local\Programs\Python\Python312\python.exe`
- Or add Python to PATH (see above)

**Port already in use:**
- Change BACKEND_PORT in .env
- Or change frontend port in package.json: `"dev": "next dev -p 3001"`

**CORS errors:**
- Verify backend is running
- Check CORS configuration in main.py
- Ensure frontend is using correct API URL

**Module not found:**
- Ensure dependencies are installed
- Activate virtual environment if using one
- Check Python path is correct

## Development Workflow

1. Start backend (Terminal 1)
2. Start frontend (Terminal 2)
3. Open http://localhost:3000 in browser
4. Make changes to code
5. Frontend hot-reloads automatically
6. Backend may need restart (or use uvicorn --reload)
