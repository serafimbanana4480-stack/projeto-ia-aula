# Deployment Guide

## Production Deployment

1. Set environment variables:
   - Copy `.env.example` to `.env.production`
   - Update with production values
   - Set `ENVIRONMENT=production`
   - Set `DEBUG=false`

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   cd frontend && npm install
   ```

3. Run with production server:
   ```bash
   gunicorn backend.orchestrator.main:app
   ```
