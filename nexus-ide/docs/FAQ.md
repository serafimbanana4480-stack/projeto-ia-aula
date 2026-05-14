# FAQ - NEXUS IDE

Frequently Asked Questions about NEXUS IDE.

## General Questions

### What is NEXUS IDE?

NEXUS IDE is an AI-assisted Integrated Development Environment that uses specialized AI agents to help with coding, analysis, debugging, and more. It runs locally with Ollama for privacy and features a modern web-based interface.

### What makes NEXUS IDE different from other AI coding assistants?

NEXUS IDE uses a multi-agent architecture where different AI agents specialize in specific tasks:
- **ROUTER**: Classifies your requests and routes to the right agent
- **CODER**: Specializes in code generation and refactoring
- **DEBUGGER**: Focuses on finding and fixing bugs
- **ARCHITECT**: Helps with system design and architecture
- **RESEARCHER**: Searches for current information
- And more specialized agents

This specialization leads to more accurate and contextually appropriate responses.

### Is NEXUS IDE free?

Yes, NEXUS IDE is open-source and free to use. However, it requires:
- Local computational resources for running AI models
- Ollama for AI model hosting
- Docker for containerized services

## Installation & Setup

### What are the system requirements?

**Minimum Requirements:**
- CPU: 4 cores
- RAM: 8GB
- Storage: 20GB free space
- GPU: Not required but recommended for AI models

**Recommended Requirements:**
- CPU: 8+ cores
- RAM: 16GB+
- Storage: 50GB+ free space
- GPU: 8GB+ VRAM (for faster AI inference)

### How do I install NEXUS IDE?

See the [Developer Setup Guide](./developer-setup.md) for detailed installation instructions.

Quick start:
```bash
git clone <repository-url>
cd nexus-ide
cp .env.example .env
bash scripts/setup.sh
```

### Do I need Ollama installed?

You can either:
1. Install Ollama locally, or
2. Use the Docker setup which includes Ollama containers

The Docker setup is recommended for easier installation.

### Can I run NEXUS IDE without Docker?

Yes, but you'll need to:
1. Install Ollama locally
2. Install Redis locally
3. Install Python and Node.js
4. Set up all dependencies manually

See the manual setup instructions in the Developer Setup Guide.

## Usage

### How do I start using NEXUS IDE?

1. Start the services: `make dev` or `docker compose up -d`
2. Open http://localhost:3000 in your browser
3. Start chatting with the AI assistant

### What can I ask NEXUS IDE to do?

You can ask NEXUS IDE to:
- Generate code in various languages
- Debug and fix errors
- Explain code and concepts
- Refactor existing code
- Architect systems and components
- Research current best practices
- Write documentation
- Optimize performance
- And much more

### How do I switch between different AI models?

NEXUS IDE automatically routes your requests to the most appropriate model based on:
- The complexity of your request
- The type of task (coding, analysis, etc.)
- Your configured preferences

You can also manually select models in the interface.

### Can I use my own AI models?

Yes, you can configure custom models in `config/models.yaml`. The system supports any Ollama-compatible model.

## Configuration

### How do I configure the AI models?

Edit `config/models.yaml` to customize:
- Which models to use for each task
- Model parameters (temperature, max tokens, etc.)
- Fallback models
- Concurrency limits

See the [Architecture Documentation](../ARCHITECTURE.md) for details.

### How do I change the port numbers?

Edit the `.env` file:
```bash
BACKEND_PORT=8001  # Change backend port
# Update NEXT_PUBLIC_API_URL accordingly
NEXT_PUBLIC_API_URL=http://localhost:8001
```

### Can I use a remote Ollama instance?

Yes, set `OLLAMA_HOST` in `.env` to your remote Ollama instance URL:
```bash
OLLAMA_HOST=http://your-remote-server:11434
```

## Performance

### Why is NEXUS IDE slow?

Performance depends on:
- AI model size (larger models are slower)
- Your hardware (CPU/GPU/RAM)
- Network latency (if using remote services)
- Concurrent requests

To improve performance:
- Use smaller models for development
- Ensure you have sufficient RAM
- Use a GPU for AI inference
- Reduce concurrent requests

### How can I make it faster?

1. Use smaller models in `config/models.yaml`
2. Enable caching in configuration
3. Use a GPU if available
4. Close unnecessary applications
5. Increase system RAM if possible

### What AI models should I use?

For development:
- **micro** (qwen2.5:0.5b): Fast, simple tasks
- **fast** (qwen2.5:3b): Quick responses
- **coder** (qwen2.5-coder:7b): Code generation

For production:
- **reasoning** (deepseek-r1:14b): Complex tasks
- **deep** (qwen2.5:32b): Architecture and analysis

## Troubleshooting

### NEXUS IDE won't start

1. Check if Docker is running: `docker ps`
2. Check if ports are available: `lsof -i :3000` and `lsof -i :8000`
3. Check logs: `docker logs nexus-backend`
4. Validate configuration: `python scripts/validate_config.py`

See the [Troubleshooting Guide](./troubleshooting.md) for more details.

### AI models aren't working

1. Check if Ollama is running: `curl http://localhost:11434/api/tags`
2. Check if models are downloaded: `docker exec nexus-ollama-main ollama list`
3. Pull missing models: `docker exec nexus-ollama-main ollama pull <model-name>`
4. Check Ollama logs: `docker logs nexus-ollama-main`

### Database errors

1. Ensure data directory exists: `mkdir -p data`
2. Check database permissions
3. Reinitialize database: `python -c "from backend.persistence import init_db; init_db()"`
4. Check disk space

## Security

### Is NEXUS IDE secure?

NEXUS IDE includes several security features:
- Input validation and sanitization
- Rate limiting
- Docker sandbox for code execution
- No data leaves your local environment (when using local Ollama)

However, it's still in development and should not be used with sensitive data without additional security measures.

### Can I use NEXUS IDE with sensitive code?

While NEXUS IDE runs locally, you should:
- Keep your `.env` file secure
- Use strong secret keys in production
- Implement authentication before deployment
- Review the code before trusting AI suggestions
- Be cautious with code execution features

## Integration

### Can I use NEXUS IDE with my existing projects?

Yes, NEXUS IDE can work with any local project. The desktop app allows you to select any folder on your system.

### Does it integrate with Git?

NEXUS IDE doesn't include built-in Git integration, but you can use Git commands in the terminal or integrate Git operations through the agent system.

### Can I use it with VS Code?

NEXUS IDE is a standalone IDE. However, you can use similar AI assistant extensions in VS Code if you prefer that workflow.

## Development

### How can I contribute to NEXUS IDE?

See the [CONTRIBUTING.md](../CONTRIBUTING.md) file for contribution guidelines.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Write tests
5. Submit a pull request

### What tech stack does NEXUS IDE use?

- **Backend**: Python 3.12, FastAPI, Uvicorn
- **Frontend**: Next.js 15, React 19, TypeScript, Tailwind CSS
- **Desktop**: Electron
- **AI**: Ollama with various models
- **Database**: SQLite (with PostgreSQL support planned)
- **Cache**: Redis
- **Observability**: OpenTelemetry, Prometheus
- **Containerization**: Docker, Docker Compose

## Support

### Where can I get help?

- Check the [documentation](../README.md)
- Review [troubleshooting guide](./troubleshooting.md)
- Run diagnostics: `make selftest`
- Check existing GitHub issues
- Create a new issue with detailed information

### How do I report bugs?

Report bugs through the project's issue tracker with:
- Description of the problem
- Steps to reproduce
- Expected vs actual behavior
- System information
- Logs and error messages

## Future Plans

### What features are planned?

See the [PLANO_MELHORIAS.md](../PLANO_MELHORIAS.md) for the roadmap and planned improvements.

Planned features include:
- Enhanced security and authentication
- PostgreSQL support
- Advanced debugging tools
- Improved performance
- Expanded testing coverage
- Enhanced documentation

### When will version 1.0 be released?

There's no set release date for version 1.0. The project is currently in active development. Follow the repository for updates.

## License

### What license is NEXUS IDE under?

Check the LICENSE file in the repository for license information.

---

Still have questions? Please check the [documentation](../README.md) or [create an issue](https://github.com/your-repo/issues).