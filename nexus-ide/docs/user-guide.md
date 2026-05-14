# User Guide - NEXUS IDE

Welcome to NEXUS IDE, your AI-powered development environment. This guide will help you get started and make the most of all features.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Interface Overview](#interface-overview)
3. [Chat with AI](#chat-with-ai)
4. [AI Agents](#ai-agents)
5. [Code Editor](#code-editor)
6. [Dashboard](#dashboard)
7. [Projects](#projects)
8. [Settings](#settings)
9. [Tips and Best Practices](#tips-and-best-practices)
10. [Troubleshooting](#troubleshooting)

## Getting Started

### First Time Setup

1. **Start NEXUS IDE**
   ```bash
   cd nexus-ide
   make dev
   # or
   docker compose -f docker/docker-compose.yml up -d
   ```

2. **Open Your Browser**
   Navigate to: http://localhost:3000

3. **Create Your First Project**
   - Click "New Project" in the sidebar
   - Name your project
   - Select a project folder
   - Choose your preferred mode

### Quick Start

1. **Start Chatting**: Simply type your question or request in the chat input
2. **Choose a Mode**: Select Auto, Coder, Architect, or Debugger from the mode selector
3. **Get Help**: Ask anything from "How do I create a REST API?" to "Debug this function"

## Interface Overview

NEXUS IDE has a clean, modern interface with three main sections:

### Left Sidebar
- **Projects**: Access your projects
- **Files**: Browse project files
- **Documents**: View documentation
- **Database**: Inspect database content
- **Models**: View available AI models

### Center - Chat Panel
- **Chat Interface**: Main interaction area with AI
- **Message History**: View conversation history
- **Input Area**: Type your questions and requests
- **Tool Panel**: Access available tools

### Right Panel
- **Model Information**: Current AI model details
- **Performance Metrics**: Response times and token usage
- **Agent Activity**: Track which agents are working
- **Session Stats**: Current session statistics

## Chat with AI

### Basic Usage

1. **Type Your Question**
   ```
   How do I create a Python class for a user?
   ```

2. **Press Enter** or click the Send button

3. **View the Response**
   - AI agent processes your request
   - See the agent's thinking process
   - Get the final answer with code examples

### Advanced Features

#### Multi-turn Conversations
- Reference previous messages
- Build on previous answers
- Ask follow-up questions

#### Code Execution
- Ask AI to execute code
- See results in real-time
- Debug interactively

#### File Operations
- Request file reads
- Ask for file modifications
- Create new files

### Keyboard Shortcuts

- **Enter**: Send message
- **Shift+Enter**: New line
- **Ctrl+D**: Toggle dark/light theme
- **Ctrl+K**: Clear chat

## AI Agents

NEXUS IDE uses specialized AI agents for different tasks:

### Available Agents

| Agent | Best For | Model |
|-------|----------|-------|
| **CODER** | Code generation, refactoring | qwen2.5-coder:7b |
| **DEBUGGER** | Finding and fixing bugs | qwen2.5-coder:7b |
| **ARCHITECT** | System design, architecture | deepseek-r1:14b |
| **RESEARCHER** | Finding current information | qwen2.5:3b |
| **ANALYZER** | Code review, analysis | qwen2.5:32b |
| **DOCUMENTER** | Writing documentation | qwen2.5:3b |
| **OPTIMIZER** | Performance optimization | qwen2.5:3b |

### How Agents Work

1. **Router** analyzes your request
2. **Selects the best agent** for the task
3. **Agent processes** your request with appropriate tools
4. **Returns results** with thinking process visible

### Choosing Specific Agents

While the router automatically selects agents, you can:
- Use keywords to hint at specific agents
- Choose a mode that favors certain agents
- Manually request specific agent types

## Code Editor

### Monaco Editor Integration

NEXUS IDE includes a full-featured code editor based on Monaco Editor (VS Code's editor).

### Features

- **Syntax Highlighting**: Support for 100+ languages
- **IntelliSense**: Auto-completion and suggestions
- **Error Detection**: Real-time error highlighting
- **Multi-cursor**: Edit multiple lines simultaneously
- **Find and Replace**: Powerful search functionality
- **Git Integration**: View file changes

### Using the Editor

1. **Open a File**
   - Navigate to Files in the sidebar
   - Click on any file to open it

2. **Edit Code**
   - Click in the editor to start typing
   - Use keyboard shortcuts for efficiency

3. **Save Changes**
   - Ctrl+S (Cmd+S on Mac)
   - Changes are automatically saved

### AI-Powered Editing

- **Inline Suggestions**: AI suggests code as you type
- **Refactoring**: Ask AI to refactor selected code
- **Explain Code**: Highlight code and ask for explanation
- **Generate Tests**: Request unit tests for your code

## Dashboard

### Real-time Monitoring

The dashboard provides insights into system performance and AI operations.

### Metrics Available

- **System Health**: Overall system status
- **Request Flow**: Visualize request processing
- **Token Usage**: Track token consumption
- **Agent Activity**: See which agents are active
- **Response Times**: Monitor performance
- **Error Rates**: Track error occurrences

### Using the Dashboard

1. Navigate to Dashboard in the sidebar
2. View real-time metrics
3. Filter by time range
4. Drill down into specific metrics

## Projects

### Project Management

Create and manage multiple projects within NEXUS IDE.

### Creating a Project

1. Click "New Project" in the sidebar
2. Enter project name
3. Select project folder
4. Choose project mode
5. Click "Create"

### Project Modes

- **Auto**: Let AI choose the best approach
- **Coder**: Focus on code generation
- **Architect**: Focus on system design
- **Debugger**: Focus on problem-solving

### Switching Projects

1. Click on Projects in the sidebar
2. Select the project you want to switch to
3. The interface updates with project context

## Settings

### Configuration Options

Access settings to customize your NEXUS IDE experience.

### Available Settings

#### AI Settings
- **Default Model**: Choose your preferred AI model
- **Temperature**: Control response creativity (0.0-1.0)
- **Max Tokens**: Limit response length

#### Interface Settings
- **Theme**: Dark, Light, or System
- **Font Size**: Adjust editor font size
- **Panel Layout**: Customize panel positions

#### Security Settings
- **API Keys**: Manage external API keys
- **Rate Limiting**: Configure request limits
- **Allowed Origins**: Set CORS origins

### Accessing Settings

1. Click on Settings in the sidebar
2. Browse categories on the left
3. Modify settings as needed
4. Changes are saved automatically

## Tips and Best Practices

### Effective Prompting

1. **Be Specific**
   - ❌ "Help me with code"
   - ✅ "Create a Python function that validates email addresses using regex"

2. **Provide Context**
   - ❌ "Fix this bug"
   - ✅ "I'm getting a TypeError in my user authentication function. Here's the code..."

3. **Request Format**
   - ❌ "Write code"
   - ✅ "Write a Python class with proper docstrings and type hints"

### Getting Better Results

1. **Start Simple**: Begin with basic requests
2. **Iterate**: Refine your request based on responses
3. **Provide Examples**: Show what you want
4. **Use Follow-ups**: Build on previous answers
5. **Check Code**: Always review AI-generated code

### Performance Tips

1. **Use Appropriate Models**: Smaller models for simple tasks
2. **Clear History**: Clear chat when starting new tasks
3. **Be Specific**: Specific requests get faster responses
4. **Use Modes**: Choose the right mode for your task

## Troubleshooting

### Common Issues

#### AI Not Responding

**Problem**: AI doesn't respond to your request

**Solutions**:
- Check if Ollama is running: `docker ps | grep ollama`
- Verify model is downloaded: `docker exec nexus-ollama-main ollama list`
- Check backend logs: `docker logs nexus-backend`
- Refresh the page and try again

#### Slow Responses

**Problem**: AI takes too long to respond

**Solutions**:
- Use a smaller model
- Reduce request complexity
- Check system resources
- Close unnecessary applications

#### Code Errors

**Problem**: Generated code doesn't work

**Solutions**:
- Ask AI to debug the code
- Provide error messages
- Request alternative approaches
- Check for missing dependencies

### Getting Help

- Check the [Troubleshooting Guide](./troubleshooting.md)
- Review [FAQ](./FAQ.md)
- Run diagnostics: `make selftest`
- Check logs: `docker logs nexus-backend`

## Advanced Features

### Web Search

The AI agent can search the web for current information:

```
Search for the latest Python best practices for API design
```

### Code Execution

Execute code in a safe sandbox:

```
Run this Python code and show me the output:
def calculate_fibonacci(n):
    if n <= 1:
        return n
    return calculate_fibonacci(n-1) + calculate_fibonacci(n-2)

print(calculate_fibonacci(10))
```

### File Operations

Ask AI to work with files:

```
Read the file backend/orchestrator/main.py and suggest improvements
```

```
Create a new Python file called utils.py with helper functions
```

## Keyboard Shortcuts Reference

| Shortcut | Action |
|----------|--------|
| Enter | Send message |
| Shift+Enter | New line in chat |
| Ctrl+D | Toggle theme |
| Ctrl+K | Clear chat |
| Ctrl+S | Save file |
| Ctrl+F | Find in editor |
| Ctrl+H | Find and replace |
| Ctrl+/ | Toggle comment |
| F5 | Run code (if available) |

## Next Steps

Now that you're familiar with NEXUS IDE:

1. **Explore**: Try different features and modes
2. **Customize**: Adjust settings to your preference
3. **Create**: Build your first project with AI assistance
4. **Learn**: Check out the [Developer Guide](./developer-setup.md) for advanced usage

## Additional Resources

- [Architecture Documentation](../ARCHITECTURE.md)
- [Developer Setup Guide](./developer-setup.md)
- [Troubleshooting Guide](./troubleshooting.md)
- [FAQ](./FAQ.md)
- [API Documentation](http://localhost:8000/docs) (when running)

---

**Happy coding with NEXUS IDE! 🚀**