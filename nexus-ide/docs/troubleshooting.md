# Troubleshooting Guide - NEXUS IDE

## Common Issues and Solutions

### Configuration Issues

#### Issue: `.env` file does not exist
**Error**: `FileNotFoundError: .env file not found`

**Solution**:
```bash
cd nexus-ide
cp .env.example .env
# Edit .env with your specific configuration
```

#### Issue: Configuration validation fails
**Error**: `Configuration validation failed`

**Solution**:
```bash
# Run validation script to see specific issues
python scripts/validate_config.py

# Ensure all required environment variables are set in .env
# Check that .env file exists in the nexus-ide directory
```

### Database Issues

#### Issue: SQLite database file not found
**Error**: `sqlite3.OperationalError: unable to open database file`

**Solution**:
```bash
# Create data directory
mkdir -p data

# The database will be automatically created on first run
# Or initialize manually:
python -c "from backend.persistence import init_db; init_db()"
```

#### Issue: Database locked
**Error**: `sqlite3.OperationalError: database is locked`

**Solution**:
```bash
# Ensure only one instance of the backend is running
# Check for running processes:
ps aux | grep uvicorn

# Kill any running backend instances
pkill -f uvicorn

# Restart the backend
make backend
```

### Ollama Issues

#### Issue: Ollama connection refused
**Error**: `Connection refused: Ollama not responding`

**Solution**:
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# If not running, start Ollama:
# Using Docker:
docker compose -f docker/docker-compose.yml up ollama-main

# Or if installed locally:
ollama serve
```

#### Issue: Model not found
**Error**: `Model 'qwen2.5:0.5b' not found`

**Solution**:
```bash
# Pull the required model
docker exec nexus-ollama-main ollama pull qwen2.5:0.5b

# Or pull all models using the setup script
bash scripts/setup.sh

# List available models
docker exec nexus-ollama-main ollama list
```

### Backend Issues

#### Issue: Backend fails to start
**Error**: `Address already in use: port 8000`

**Solution**:
```bash
# Check what's using port 8000
lsof -i :8000

# Kill the process using the port
kill -9 <PID>

# Or change the port in .env:
BACKEND_PORT=8001
```

#### Issue: Import errors
**Error**: `ModuleNotFoundError: No module named 'backend'`

**Solution**:
```bash
# Install backend dependencies
cd backend
pip install -r requirements.txt

# Ensure you're running from the correct directory
cd ..
python -m backend.orchestrator.main
```

### Frontend Issues

#### Issue: Frontend build fails
**Error**: `Module not found: Can't resolve '...'`

**Solution**:
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
npm run build
```

#### Issue: Cannot connect to backend
**Error**: `Network error: Failed to fetch`

**Solution**:
```bash
# Ensure backend is running
curl http://localhost:8000/health

# Check NEXT_PUBLIC_API_URL in .env
# Should match backend URL:
NEXT_PUBLIC_API_URL=http://localhost:8000

# Restart frontend
cd frontend
npm run dev
```

### Docker Issues

#### Issue: Docker containers won't start
**Error**: `Port already in use` or `Container name already in use`

**Solution**:
```bash
# Stop all containers
docker compose -f docker/docker-compose.yml down

# Remove containers (WARNING: deletes data)
docker compose -f docker/docker-compose.yml down -v

# Restart
docker compose -f docker/docker-compose.yml up -d
```

#### Issue: Out of memory
**Error**: `OOMKilled` or similar memory errors

**Solution**:
```bash
# Check Docker memory usage
docker stats

# Increase Docker memory allocation in Docker Desktop settings
# Or reduce model sizes in config/models.yaml

# Use smaller models for testing
# Edit config/models.yaml to use smaller model variants
```

### Redis Issues

#### Issue: Redis connection refused
**Error**: `Connection refused: Redis not responding`

**Solution**:
```bash
# Check if Redis is running
docker ps | grep redis

# Start Redis if not running
docker compose -f docker/docker-compose.yml up redis

# Or start Redis locally
redis-server
```

### Performance Issues

#### Issue: Slow response times
**Symptoms**: API calls take >10 seconds

**Solution**:
```bash
# Check system resources
htop

# Check Ollama model loading time
docker logs nexus-ollama-main

# Use smaller/faster models for development
# Edit config/models.yaml to use 'micro' instead of 'deep'

# Enable caching in configuration
RATE_LIMIT_ENABLED=true
```

#### Issue: High memory usage
**Symptoms**: System becomes unresponsive

**Solution**:
```bash
# Check memory usage
docker stats

# Restart heavy containers
docker restart nexus-ollama-main

# Reduce concurrency limits in config/models.yaml
# Lower the concurrency values for large models
```

### Testing Issues

#### Issue: Tests fail with import errors
**Error**: `ImportError: cannot import name '...'`

**Solution**:
```bash
# Install test dependencies
cd backend
pip install -r requirements.txt

# Install frontend test dependencies
cd frontend
npm install

# Run tests from correct directory
cd ..
make test
```

#### Issue: Test database conflicts
**Error**: Database locked during tests

**Solution**:
```bash
# Use separate test database
export DATABASE_URL=sqlite:///./data/test_nexus.db

# Or run tests with database isolation
pytest --cov=. --cov-report=term-missing -v
```

## Getting Help

If you encounter issues not covered here:

1. Check the main documentation: `README.md`
2. Review architecture documentation: `ARCHITECTURE.md`
3. Check logs: `docker logs nexus-backend`, `docker logs nexus-ollama-main`
4. Run diagnostics: `make selftest`
5. Validate configuration: `python scripts/validate_config.py`

## Diagnostic Commands

```bash
# Health check
make healthcheck

# Smoke test
make smoke-test

# Self diagnostics
python scripts/selftest/run_diagnostics.py

# Validate configuration
python scripts/validate_config.py

# Check logs
docker logs nexus-backend --tail 50
docker logs nexus-ollama-main --tail 50
docker logs nexus-frontend --tail 50

# Check container status
docker compose -f docker/docker-compose.yml ps
```

## Common Environment Variables

Ensure these are set correctly in your `.env` file:

```bash
ENVIRONMENT=development
OLLAMA_HOST=http://localhost:11434
REDIS_URL=redis://localhost:6379
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
NEXT_PUBLIC_API_URL=http://localhost:8000
DATABASE_URL=sqlite:///./data/nexus.db
```

## Resetting the Project

If you need to completely reset the project:

```bash
# Stop and remove all containers
docker compose -f docker/docker-compose.yml down -v

# Clean all artifacts
make clean

# Remove node_modules and __pycache__
rm -rf frontend/node_modules backend/__pycache__

# Restart from scratch
cp .env.example .env
bash scripts/setup.sh
```