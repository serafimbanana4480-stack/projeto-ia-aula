# Developer Setup Guide - NEXUS IDE

This guide provides detailed instructions for setting up a development environment for NEXUS IDE.

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.12+** - [Download](https://www.python.org/downloads/)
- **Node.js 18+** - [Download](https://nodejs.org/)
- **Docker & Docker Compose** - [Download](https://www.docker.com/products/docker-desktop)
- **Git** - [Download](https://git-scm.com/downloads)
- **Ollama** (optional, can use Docker) - [Download](https://ollama.ai/)

## Initial Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd nexus-ide
```

### 2. Environment Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your configuration
# At minimum, ensure these variables are set:
# - ENVIRONMENT=development
# - OLLAMA_HOST=http://localhost:11434
# - REDIS_URL=redis://localhost:6379
# - BACKEND_PORT=8000
# - NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 3. Backend Setup

```bash
# Create virtual environment
cd backend
python -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Return to project root
cd ..
```

### 4. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Return to project root
cd ..
```

### 5. Docker Setup (Optional but Recommended)

```bash
# Start all services using Docker Compose
docker compose -f docker/docker-compose.yml up -d

# Or use the setup script
bash scripts/setup.sh
```

### 6. Database Initialization

```bash
# Create data directory
mkdir -p data

# Initialize database (will be done automatically on first run)
python -c "from backend.persistence import init_db; init_db()"
```

### 7. Validate Configuration

```bash
# Run configuration validation
python scripts/validate_config.py
```

## Running the Project

### Option 1: Using Docker (Recommended)

```bash
# Start all services
docker compose -f docker/docker-compose.yml up -d

# View logs
docker compose -f docker/docker-compose.yml logs -f

# Stop services
docker compose -f docker/docker-compose.yml down
```

### Option 2: Manual Startup

#### Backend Only

```bash
# Activate virtual environment
cd backend
source venv/bin/activate  # On macOS/Linux
# venv\Scripts\activate  # On Windows

# Start backend server
python -m uvicorn backend.orchestrator.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Frontend Only

```bash
cd frontend
npm run dev
```

#### Desktop App

```bash
cd desktop
npm install
npm start
```

### Option 3: Using Make Commands

```bash
# Start development environment
make dev

# Start backend only
make backend

# Start frontend only
make frontend

# Run setup
make setup
```

## Project Structure

```
nexus-ide/
├── backend/                 # Python FastAPI backend
│   ├── agents/             # AI agent implementations
│   ├── config/             # Configuration management
│   ├── orchestrator/       # Request orchestration
│   ├── persistence/        # Database layer
│   ├── tools/              # Utility tools
│   ├── tests/              # Backend tests
│   └── requirements.txt    # Python dependencies
├── frontend/               # Next.js frontend
│   ├── app/               # Next.js app directory
│   ├── components/        # React components
│   ├── hooks/             # Custom React hooks
│   ├── lib/               # Utility libraries
│   ├── stores/            # State management
│   ├── tests/             # Frontend tests
│   └── package.json       # Node dependencies
├── desktop/               # Electron desktop app
│   ├── main.js           # Electron main process
│   └── package.json      # Electron dependencies
├── config/               # Configuration files
│   ├── models.yaml       # AI model configurations
│   ├── modes.yaml        # Operation modes
│   └── prompts/          # Agent system prompts
├── docs/                 # Documentation
├── scripts/              # Utility scripts
├── docker/               # Docker configurations
└── tests/                # Integration tests
```

## Development Workflow

### 1. Making Changes

#### Backend Changes

```bash
# Edit backend files
# Backend auto-reloads with --reload flag

# Run backend tests
cd backend
pytest tests/ -v

# Run linting
ruff check .
mypy .
```

#### Frontend Changes

```bash
# Edit frontend files
# Next.js auto-reloads with npm run dev

# Run frontend tests
cd frontend
npm test

# Run linting
npm run lint
npm run type-check
```

### 2. Testing

```bash
# Run all tests
make test

# Run backend tests only
make test-backend

# Run frontend tests only
make test-frontend

# Run specific test suites
make test-agents
make test-tools
make test-orchestrator
```

### 3. Code Quality

```bash
# Run all linters
make lint

# Format code
make format

# Run type checking
cd frontend
npm run type-check
```

### 4. Database Changes

```bash
# When modifying database schema:
# 1. Update backend/persistence/schemas.sql
# 2. Create a new migration
# 3. Test migration on development database
# 4. Document migration in docs/migrations.md
```

## Configuration

### Backend Configuration

Edit `backend/config/settings.py` or use environment variables:

```bash
# In .env file
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
LOG_LEVEL=INFO
DEBUG=true
```

### AI Model Configuration

Edit `config/models.yaml` to configure AI models:

```yaml
models:
  micro:
    id: "qwen2.5:0.5b"
    max_tokens: 512
    temperature: 0.3
```

### Frontend Configuration

Edit `frontend/.env.local` or use environment variables:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Debugging

### Backend Debugging

```bash
# Run with debugger
cd backend
python -m pdb -m uvicorn backend.orchestrator.main:app --host 0.0.0.0 --port 8000

# Or use VS Code debugger
# Set breakpoints in backend code
# Run VS Code debugger with Python configuration
```

### Frontend Debugging

```bash
# Next.js includes built-in debugging
# Use Chrome DevTools for React debugging
# Install React DevTools browser extension
```

### Docker Debugging

```bash
# View container logs
docker logs nexus-backend
docker logs nexus-ollama-main
docker logs nexus-frontend

# Enter container for debugging
docker exec -it nexus-backend bash
docker exec -it nexus-ollama-main sh
```

## Common Development Tasks

### Adding a New Agent

1. Create agent file in `backend/agents/`
2. Inherit from `AgentBase`
3. Implement required methods
4. Add agent to registry in `backend/orchestrator/registry.py`
5. Create prompt in `config/prompts/<agent>.md`
6. Add tests in `backend/tests/agents/`

### Adding a New API Endpoint

1. Create route file in `backend/orchestrator/routes/`
2. Implement endpoint with FastAPI
3. Add authentication if needed
4. Write tests for the endpoint
5. Update API documentation

### Adding a New Frontend Component

1. Create component in `frontend/components/`
2. Follow existing component patterns
3. Add TypeScript types
4. Write tests for the component
5. Update documentation

### Adding a New AI Model

1. Update `config/models.yaml`
2. Pull model in Ollama
3. Test model functionality
4. Update documentation

## Troubleshooting

See [troubleshooting.md](./troubleshooting.md) for common issues and solutions.

## Performance Optimization

### Backend Optimization

- Enable caching for frequently accessed data
- Use connection pooling for database connections
- Implement async operations where possible
- Monitor performance with Prometheus metrics

### Frontend Optimization

- Use React.memo for expensive components
- Implement virtual scrolling for long lists
- Lazy load components with React.lazy()
- Optimize images and assets

## Deployment

### Development Deployment

```bash
# Use Docker Compose for development
docker compose -f docker/docker-compose.yml up -d
```

### Production Deployment

See production deployment guide (TODO: create production deployment guide)

## Contributing

1. Create a new branch for your feature
2. Make your changes following the code style
3. Write tests for your changes
4. Ensure all tests pass
5. Update documentation
6. Submit a pull request

See [CONTRIBUTING.md](../CONTRIBUTING.md) for detailed contribution guidelines.

## Additional Resources

- [Architecture Documentation](../ARCHITECTURE.md)
- [API Documentation](http://localhost:8000/docs) (when running)
- [Project README](../README.md)
- [Troubleshooting Guide](./troubleshooting.md)

## Getting Help

- Check documentation in `docs/`
- Review existing issues in the repository
- Run diagnostics: `make selftest`
- Validate configuration: `python scripts/validate_config.py`