# NEXUS IDE Documentation

Welcome to the NEXUS IDE documentation hub. This index provides quick access to all documentation resources.

## 📚 Documentation Index

### Getting Started

| Document | Description | Audience |
|----------|-------------|----------|
| [User Guide](./user-guide.md) | Complete user manual with features and tutorials | Users |
| [Developer Setup Guide](./developer-setup.md) | Development environment setup and workflow | Developers |
| [FAQ](./FAQ.md) | Frequently asked questions and solutions | All |

### Technical Documentation

| Document | Description | Audience |
|----------|-------------|----------|
| [Architecture](../ARCHITECTURE.md) | System architecture and design decisions | Developers |
| [Troubleshooting](./troubleshooting.md) | Common issues and solutions | All |
| [Contributing](../CONTRIBUTING.md) | Contribution guidelines and workflow | Developers |

### Project Documentation

| Document | Description | Location |
|----------|-------------|----------|
| Main README | Project overview and quick start | `/README.md` |
| Improvement Plan | Roadmap and planned features | `/PLANO_MELHORIAS.md` |
| Configuration | Models and modes configuration | `/config/` |

## 🚀 Quick Start

### For Users

1. Read the [User Guide](./user-guide.md)
2. Check the [FAQ](./FAQ.md) for common questions
3. Refer to [Troubleshooting](./troubleshooting.md) if you encounter issues

### For Developers

1. Read the [Developer Setup Guide](./developer-setup.md)
2. Review the [Architecture](../ARCHITECTURE.md)
3. Check [Contributing](../CONTRIBUTING.md) for guidelines

## 📖 Documentation by Topic

### Installation & Setup
- [User Guide - Getting Started](./user-guide.md#getting-started)
- [Developer Setup Guide](./developer-setup.md#initial-setup)
- [FAQ - Installation](./FAQ.md#installation--setup)

### Configuration
- [Developer Setup Guide - Configuration](./developer-setup.md#configuration)
- [Troubleshooting - Configuration Issues](./troubleshooting.md#configuration-issues)
- [FAQ - Configuration](./FAQ.md#configuration)

### AI & Models
- [User Guide - AI Agents](./user-guide.md#ai-agents)
- [Architecture - Model Matrix](../ARCHITECTURE.md#2-model-matrix)
- [FAQ - AI Models](./FAQ.md#what-ai-models-should-i-use)

### Development
- [Developer Setup Guide](./developer-setup.md)
- [Architecture](../ARCHITECTURE.md)
- [Contributing](../CONTRIBUTING.md)

### Troubleshooting
- [Troubleshooting Guide](./troubleshooting.md)
- [FAQ - Troubleshooting](./FAQ.md#troubleshooting)
- [Developer Setup - Debugging](./developer-setup.md#debugging)

## 🔍 Quick Reference

### Essential Commands

```bash
# Start development environment
make dev

# Run tests
make test

# Validate configuration
python scripts/validate_config.py

# Health check
make healthcheck

# Clean artifacts
make clean
```

### Key Files

| File | Purpose |
|------|---------|
| `.env` | Environment configuration |
| `config/models.yaml` | AI model configuration |
| `config/modes.yaml` | Operation modes |
| `backend/requirements.txt` | Python dependencies |
| `frontend/package.json` | Node dependencies |

### Important URLs (when running)

| Service | URL |
|---------|-----|
| Main Application | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Documentation | http://localhost:8000/docs |
| Dashboard | http://localhost:3000/dashboard |
| Prometheus | http://localhost:9090 |

## 🛠️ Common Tasks

### Setup Development Environment
→ [Developer Setup Guide](./developer-setup.md#initial-setup)

### Configure AI Models
→ [Developer Setup Guide - Configuration](./developer-setup.md#configuration)

### Run Tests
→ [Developer Setup Guide - Testing](./developer-setup.md#testing)

### Debug Issues
→ [Troubleshooting Guide](./troubleshooting.md)

### Contribute to Project
→ [Contributing Guide](../CONTRIBUTING.md)

### Deploy to Production
→ [TODO: Production Deployment Guide]

## 📝 Documentation Standards

When contributing to documentation:

1. **Use Clear Language**: Write for your audience
2. **Include Examples**: Show, don't just tell
3. **Keep Updated**: Maintain accuracy
4. **Cross-Reference**: Link to related docs
5. **Use Consistent Formatting**: Follow existing patterns

## 🆘 Getting Help

If you can't find what you're looking for:

1. **Search**: Use Ctrl+F to search within documents
2. **Check FAQ**: Review [FAQ](./FAQ.md) for common questions
3. **Troubleshoot**: Check [Troubleshooting Guide](./troubleshooting.md)
4. **Ask**: Create an issue on GitHub
5. **Diagnostics**: Run `make selftest`

## 📊 Documentation Status

| Document | Status | Last Updated |
|----------|--------|--------------|
| User Guide | ✅ Complete | 2026-05-13 |
| Developer Setup | ✅ Complete | 2026-05-13 |
| FAQ | ✅ Complete | 2026-05-13 |
| Troubleshooting | ✅ Complete | 2026-05-13 |
| Architecture | ✅ Complete | - |
| Contributing | ✅ Complete | - |

## 🔗 External Resources

- [Next.js Documentation](https://nextjs.org/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Ollama Documentation](https://ollama.ai/docs)
- [Docker Documentation](https://docs.docker.com/)

## 📈 Documentation Metrics

- **Total Documents**: 8
- **Total Topics Covered**: 50+
- **Code Examples**: 100+
- **Troubleshooting Solutions**: 30+
- **FAQ Items**: 40+

---

**Last Updated**: 2026-05-13

For questions or suggestions about documentation, please open an issue or pull request.