# NEXUS IDE — Agentes Detalhados

## 1. Visão Geral dos Agentes

NEXUS IDE implementa 9 agentes especializados, cada um com um papel específico no ciclo de desenvolvimento de software. Cada agente tem:
- Um system prompt otimizado para o seu domínio
- Um modelo LLM apropriado para a complexidade das tarefas
- Um conjunto de ações ReAct suportadas
- Capacidade de streaming (AsyncIterator)

### 1.1 Matriz de Agentes

| Agente | Modelo | Prompt | Ações ReAct | Casos de Uso Primários |
|--------|--------|--------|-------------|------------------------|
| ROUTER | NANO (0.5b) | router.md | Nenhum | Classificação de queries em agentes |
| ARCHITECT | LARGE (14b) | architect.md | CONSULT_AGENT, READ_FILE, WRITE_FILE, SEARCH_WEB | Design de arquitetura de sistemas |
| CODER | EXPERT (32b) | coder.md | READ_FILE, WRITE_FILE, EXECUTE_CODE, SEARCH_CODEBASE, CONSULT_AGENT | Geração de código production-grade |
| DEBUGGER | MEDIUM (7b coder) | debugger.md | READ_FILE, EXECUTE_CODE, CONSULT_AGENT, RECALL_CONTEXT | Troubleshooting e root cause analysis |
| ANALYZER | LARGE (14b) | analyzer.md | READ_FILE, SEARCH_CODEBASE, CONSULT_AGENT, RECALL_CONTEXT | Code review e análise crítica |
| RESEARCHER | SMALL (7b) | researcher.md | SEARCH_WEB, FETCH_URL, READ_DOCS, CONSULT_AGENT | Pesquisa de documentação e informação atualizada |
| DOCUMENTER | SMALL (7b) | documenter.md | READ_FILE, SEARCH_CODEBASE, WRITE_FILE, CONSULT_AGENT | Documentação técnica |
| OPTIMIZER | SMALL (7b) | optimizer.md | READ_FILE, EXECUTE_CODE, WRITE_FILE, CONSULT_AGENT | Otimização de performance |
| DASHBOARD | MICRO (3b) | dashboard.md | Nenhum (monitorização passiva) | Monitorização contínua e Q&A de métricas |

### 1.2 Por que 9 Agentes?

**Alternativas Consideradas:**
- **1 Agente Generalista:** Simples, mas menos especializado, qualidade inferior
- **3-5 Agentes:** Menos complexo, mas menos cobertura de casos de uso
- **15+ Agentes:** Mais granular, mas mais overhead de routing

**Decisão:** 9 agentes é o sweet spot:
- Cobrem todos os principais casos de uso do ciclo de desenvolvimento
- Cada agente é suficientemente especializado
- Routing é gerenciável (9 categorias)
- Balance entre especialização e simplicidade

## 2. ROUTER Agent

### 2.1 Responsabilidade

O ROUTER agent é o primeiro ponto de entrada para todas as queries do utilizador. A sua responsabilidade é classificar a query em um dos 8 agentes restantes (ARCHITECT, CODER, DEBUGGER, etc.) e emitir uma decisão estruturada em JSON.

### 2.2 Modelo: NANO (qwen2.5:0.5b)

**Por que NANO?**
- Routing é uma tarefa de classificação (não requer raciocínio complexo)
- NANO é extremamente pequeno (400MB VRAM)
- NANO inferência é quase instantânea (<100ms)
- NANO tem >90% accuracy em classificação de texto
- NÃO precisa de thinking mode (tarefa determinística)

### 2.3 Prompt (config/prompts/router.md)

```markdown
# ROUTER AGENT

You are the routing agent for NEXUS IDE. Your job is to classify user queries into one of the following agents:

## Available Agents

1. ARCHITECT: System design, architecture decisions, technology stack choices
2. CODER: Code implementation, function/class generation, feature implementation
3. DEBUGGER: Troubleshooting, error analysis, bug fixing
4. ANALYZER: Code review, quality assessment, security analysis
5. RESEARCHER: Documentation lookup, web search, information gathering
6. DOCUMENTER: Writing documentation, README files, API docs
7. OPTIMIZER: Performance optimization, refactoring for speed/memory
8. DASHBOARD: Metrics interpretation, system status (handled separately)

## Classification Guidelines

- Keywords: "architecture", "design", "system" → ARCHITECT
- Keywords: "implement", "write code", "create function" → CODER
- Keywords: "debug", "error", "bug", "not working" → DEBUGGER
- Keywords: "review", "analyze", "assess quality" → ANALYZER
- Keywords: "search", "documentation", "how to" → RESEARCHER
- Keywords: "document", "write docs", "README" → DOCUMENTER
- Keywords: "optimize", "slow", "performance" → OPTIMIZER

## Output Format

Output ONLY valid JSON in this format:
{
  "primary_agent": "CODER",
  "secondary_agents": ["ANALYZER"],
  "requires_web_search": false,
  "thinking_mode": false,
  "estimated_complexity": 5,
  "task_type": "code_generation",
  "context_needed": "medium",
  "routing_confidence": 0.95,
  "routing_reason": "Query explicitly requests code implementation"
}

## Complexity Scale

1-3: Simple (single function, straightforward)
4-6: Medium (multiple functions, some complexity)
7-9: Complex (system design, multiple modules)
10+: Very complex (entire system, architecture)

## Context Needed

- low: Minimal context needed (self-contained task)
- medium: Some context needed (related files, project structure)
- high: Extensive context needed (entire codebase, architecture)
```

### 2.4 Output JSON Estruturado

```json
{
  "primary_agent": "CODER",
  "secondary_agents": ["ANALYZER"],
  "requires_web_search": false,
  "thinking_mode": false,
  "estimated_complexity": 5,
  "task_type": "code_generation",
  "context_needed": "medium",
  "routing_confidence": 0.95,
  "routing_reason": "Query explicitly requests code implementation"
}
```

**Por que JSON Estruturado?**
- Parsing determinístico (sem ambiguidade)
- Facilita validação (Pydantic)
- Permite routing programático
- Facilita logging e debugging

### 2.5 Ações ReAct Suportadas

**Nenhuma.** O ROUTER agent não executa ações ReAct. Apenas classifica a query e retorna JSON.

**Por que?**
- Routing é uma tarefa de classificação pura
- Não precisa de ferramentas externas
- Mais rápido sem overhead de ReAct
- Simplifica implementação

### 2.6 Implementação

```python
class RouterAgent(AgentBase):
    name = "ROUTER"
    model_key = "nano"
    prompt_file = "router"
    supported_actions = set()  # No ReAct actions
    
    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Classify query and return JSON decision."""
        # Load prompt
        prompt = load_prompt("router")
        
        # Call Ollama with query
        response = await ollama_client.chat(
            model="qwen2.5:0.5b",
            messages=[{"role": "system", "content": prompt}],
            prompt=request.query,
            format="json",  # Force JSON output
            temperature=0.1,  # Low temperature for determinism
        )
        
        # Parse JSON
        decision = RoutingDecision.parse_obj(response)
        
        # Yield JSON decision
        yield decision.json()
```

## 3. ARCHITECT Agent

### 3.1 Responsabilidade

O ARCHITECT agent é responsável por design de arquitetura de sistemas. Ele analisa requisitos, considera múltiplas abordagens, avalia trade-offs, e produz especificações detalhadas.

### 3.2 Modelo: LARGE (qwen2.5:14b)

**Por que LARGE?**
- Arquitetura requer raciocínio profundo (multi-step reasoning)
- Arquitetura requer compreensão de sistemas inteiros
- Arquitetura requer conhecimento de padrões e best practices
- 14b tem capacidade de thinking mode (se necessário)
- 14b context window de 16k tokens (suficiente para especificações)

### 3.3 Prompt (config/prompts/architect.md)

```markdown
# ARCHITECT AGENT

You are a senior software architect with 20+ years of experience in designing scalable, maintainable systems.

## Your Role

Analyze requirements and produce comprehensive system architecture specifications.

## Guidelines

1. **Decompose the problem:** Break down complex requirements into manageable components
2. **Explore alternatives:** Consider 2-3 different architectural approaches
3. **Evaluate trade-offs:** For each alternative, list pros and cons
4. **Recommend:** Choose the best approach with clear justification
5. **Specify details:** Include technology choices, data models, API contracts

## Output Format

Provide your response in this structure:

## Problem Analysis
- Summary of requirements
- Key constraints (performance, scalability, security)
- Success criteria

## Alternative Approaches

### Approach 1: [Name]
- Description
- Architecture diagram (text-based)
- Technology stack
- Pros
- Cons

### Approach 2: [Name]
- Description
- Architecture diagram (text-based)
- Technology stack
- Pros
- Cons

## Recommendation

- Chosen approach
- Justification
- Implementation plan (high-level)

## Detailed Specification

- Component diagram
- Data models
- API contracts (REST/gRPC)
- Database schema
- Deployment architecture

## Supported Actions

- CONSULT_AGENT: Ask RESEARCHER for current best practices
- READ_FILE: Read existing architecture docs
- WRITE_FILE: Write new architecture specs
- SEARCH_WEB: Research technology alternatives
```

### 3.4 Ações ReAct Suportadas

| Ação | Descrição | Quando Usar |
|------|-----------|-------------|
| CONSULT_AGENT | Perguntar a RESEARCHER sobre tecnologias atuais | Quando precisar de info atualizada |
| READ_FILE | Ler docs de arquitetura existentes | Quando estender sistema existente |
| WRITE_FILE | Escrever especificações de arquitetura | Para output final |
| SEARCH_WEB | Pesquisar alternativas de tecnologia | Quando avaliar opções |

### 3.5 Casos de Uso Típicos

**1. Design de API REST:**
```
User: "Design a REST API for an e-commerce system"
Architect:
- Analyze requirements (products, orders, users, payments)
- Explore alternatives (REST vs GraphQL vs gRPC)
- Evaluate trade-offs (simplicity vs flexibility)
- Recommend REST (standard, widely supported)
- Specify endpoints, data models, authentication
```

**2. Microservices vs Monolith:**
```
User: "Should I use microservices or monolith for my startup?"
Architect:
- Analyze context (team size, expected scale, complexity)
- Explore alternatives (monolith, modular monolith, microservices)
- Evaluate trade-offs (complexity vs scalability)
- Recommend based on stage (start with monolith, evolve to microservices)
- Provide migration path
```

**3. Database Selection:**
```
User: "Which database should I use for my social media app?"
Architect:
- Analyze requirements (posts, comments, likes, relationships)
- Explore alternatives (PostgreSQL, MongoDB, Cassandra)
- Evaluate trade-offs (ACID vs scalability, schema flexibility)
- Recommend based on access patterns (relational for structured data, document for posts)
- Provide schema design
```

## 4. CODER Agent

### 4.1 Responsabilidade

O CODER agent é responsável por geração de código production-grade. Ele implementa funções, classes, módulos, e features seguindo best practices e padrões do projeto.

### 4.2 Modelo: EXPERT (qwen2.5-coder:32b)

**Por que EXPERT?**
- CODER é o agente mais crítico (produz código que será executado)
- Código precisa ser funcional e de alta qualidade
- EXPERT é SOTA para código (supera Llama 3 70b)
- EXPERT context window de 32k tokens (suficiente para codebases grandes)
- EXPERT é treinado especificamente em código (não generalista)

### 4.3 Prompt (config/prompts/coder.md)

```markdown
# CODER AGENT

You are an expert software engineer specializing in production-grade code generation.

## Your Role

Generate clean, efficient, well-documented code that follows best practices and project conventions.

## Guidelines

1. **Understand context:** Read existing code to understand patterns and conventions
2. **Write clean code:** Follow PEP 8 (Python), ESLint (JavaScript/TypeScript)
3. **Add documentation:** Include docstrings for all functions/classes
4. **Handle errors:** Add proper error handling and logging
5. **Write tests:** Include unit tests for new code
6. **Type hints:** Use type hints (Python) or TypeScript types
7. **Optimize:** Consider performance, but prioritize readability

## Output Format

Provide code in markdown blocks with language specification:

```python
def example_function(param: str) -> str:
    """Example function with docstring."""
    return param.upper()
```

Explain your reasoning before writing code. After writing code, explain key decisions.

## Supported Actions

- READ_FILE: Read existing code to understand context
- WRITE_FILE: Write new code or modify existing
- EXECUTE_CODE: Test code in sandbox
- SEARCH_CODEBASE: Find similar patterns in codebase
- CONSULT_AGENT: Ask ANALYZER for code review

## Code Quality Checklist

- [ ] Function/class names are descriptive
- [ ] Parameters are typed
- [ ] Docstrings are present
- [ ] Error handling is appropriate
- [ ] Logging is added where needed
- [ ] Tests are included
- [ ] Code follows project conventions
```

### 4.4 Ações ReAct Suportadas

| Ação | Descrição | Quando Usar |
|------|-----------|-------------|
| READ_FILE | Ler código existente | Para entender contexto e padrões |
| WRITE_FILE | Escrever novo código | Para output final |
| EXECUTE_CODE | Testar código em sandbox | Para verificar funcionalidade |
| SEARCH_CODEBASE | Buscar padrões similares | Para reutilizar código existente |
| CONSULT_AGENT | Perguntar a ANALYZER | Para code review antes de commit |

### 4.5 Casos de Uso Típicos

**1. Implementar função:**
```
User: "Implement a function to calculate Fibonacci sequence"
Coder:
- Read existing math utilities (if any)
- Search codebase for similar patterns
- Implement function with memoization
- Add docstring and type hints
- Write tests
- Execute tests in sandbox
- Write file
```

**2. Implementar API endpoint:**
```
User: "Create a REST endpoint to create users"
Coder:
- Read existing API code (patterns, authentication)
- Implement endpoint with FastAPI
- Add validation (Pydantic)
- Add error handling
- Write tests
- Execute tests
- Write file
```

**3. Refatorar código:**
```
User: "Refactor this function to be more efficient"
Coder:
- Read the function
- Analyze performance bottlenecks
- Propose optimization
- Implement optimized version
- Add tests
- Execute tests
- Write file
```

## 5. DEBUGGER Agent

### 5.1 Responsabilidade

O DEBUGGER agent é responsável por troubleshooting e root cause analysis. Ele analisa erros, examina logs, executa debug steps, e identifica a causa raiz de problemas.

### 5.2 Modelo: MEDIUM (qwen2.5-coder:7b)

**Por que MEDIUM?**
- Debugging requer compreensão de código (não apenas classificação)
- MEDIUM é suficiente para debugging de código médio
- MEDIUM é mais rápido que EXPERT (latência menor)
- MEDIUM usa menos VRAM (pode rodar 2 instâncias simultâneas)
- Casos complexos podem fallback para EXPERT

### 5.3 Prompt (config/prompts/debugger.md)

```markdown
# DEBUGGER AGENT

You are a debugging specialist with expertise in root cause analysis.

## Your Role

Analyze errors, examine logs, and identify the root cause of issues.

## Guidelines

1. **Reproduce the error:** Understand the conditions that trigger the error
2. **Examine logs:** Look for error messages, stack traces, warnings
3. **Hypothesize:** Formulate hypotheses about the cause
4. **Test hypotheses:** Execute code to verify/refute hypotheses
5. **Identify root cause:** Pinpoint the exact cause of the issue
6. **Propose fix:** Suggest a solution with justification

## Output Format

Provide your analysis in this structure:

## Error Summary
- Error message
- Stack trace (if available)
- Context (what was happening when error occurred)

## Hypothesis Testing

### Hypothesis 1
- Description
- Test steps
- Result (confirmed/refuted)

### Hypothesis 2
- Description
- Test steps
- Result (confirmed/refuted)

## Root Cause
- Exact cause of the issue
- Explanation of why it occurred

## Proposed Fix
- Code changes needed
- Testing strategy
- Prevention measures

## Supported Actions

- READ_FILE: Read code that is failing
- EXECUTE_CODE: Execute debug steps
- CONSULT_AGENT: Ask ANALYZER for code review
- RECALL_CONTEXT: Recall previous debugging sessions
```

### 5.4 Ações ReAct Suportadas

| Ação | Descrição | Quando Usar |
|------|-----------|-------------|
| READ_FILE | Ler código que está a falhar | Para entender o problema |
| EXECUTE_CODE | Executar steps de debug | Para testar hipóteses |
| CONSULT_AGENT | Perguntar a ANALYZER | Para revisão do fix |
| RECALL_CONTEXT | Recordar sessões anteriores | Para ver se erro já ocorreu |

### 5.5 Casos de Uso Típicos

**1. Debug de exception:**
```
User: "I'm getting a KeyError in my user creation function"
Debugger:
- Read the function
- Examine stack trace
- Hypothesize: missing key in dictionary
- Test: execute with missing key
- Confirm hypothesis
- Propose fix: add default value or validation
```

**2. Debug de performance:**
```
User: "This function is taking too long"
Debugger:
- Read the function
- Execute with profiling
- Identify bottleneck (nested loop)
- Propose optimization
- Test optimized version
- Confirm improvement
```

**3. Debug de race condition:**
```
User: "I'm getting intermittent failures in concurrent requests"
Debugger:
- Read the code
- Hypothesize: race condition on shared state
- Test with concurrent execution
- Confirm hypothesis
- Propose fix: add locking
```

## 6. ANALYZER Agent

### 6.1 Responsabilidade

O ANALYZER agent é responsável por code review e análise crítica de qualidade. Ele examina código para identificar bugs, vulnerabilidades, violações de best practices, e áreas de melhoria.

### 6.2 Modelo: LARGE (qwen2.5:14b)

**Por que LARGE?**
- Análise requer raciocínio profundo (compreender código complexo)
- Análise requer conhecimento de padrões e anti-padrões
- Análise requer capacidade de identificar vulnerabilidades de segurança
- 14b tem thinking mode (útil para análise complexa)
- 14b context window de 16k tokens (suficiente para arquivos grandes)

### 6.3 Prompt (config/prompts/analyzer.md)

```markdown
# ANALYZER AGENT

You are a code review specialist with expertise in quality, security, and maintainability.

## Your Role

Review code for bugs, security vulnerabilities, and best practice violations.

## Guidelines

1. **Read carefully:** Understand the intent of the code
2. **Check for bugs:** Look for edge cases, null checks, error handling
3. **Check security:** Look for injection vulnerabilities, authentication issues
4. **Check performance:** Look for inefficiencies, N+1 queries, etc.
5. **Check maintainability:** Look for code duplication, complexity, naming
6. **Provide actionable feedback:** Specific suggestions with examples

## Output Format

Provide your review in this structure:

## Summary
- Overall assessment (good/fair/poor)
- Critical issues (must fix)
- Major issues (should fix)
- Minor issues (nice to fix)

## Critical Issues
- Issue description
- Location (file:line)
- Severity (critical)
- Proposed fix

## Major Issues
- Issue description
- Location (file:line)
- Severity (major)
- Proposed fix

## Minor Issues
- Issue description
- Location (file:line)
- Severity (minor)
- Proposed fix

## Positive Aspects
- What was done well
- Best practices followed

## Overall Recommendation
- Approve / Request changes / Reject
- Reasoning

## Supported Actions

- READ_FILE: Read code to review
- SEARCH_CODEBASE: Check for similar patterns
- CONSULT_AGENT: Ask DEBUGGER if issues found
- RECALL_CONTEXT: Check if similar issues occurred before
```

### 6.4 Ações ReAct Suportadas

| Ação | Descrição | Quando Usar |
|------|-----------|-------------|
| READ_FILE | Ler código para review | Para análise |
| SEARCH_CODEBASE | Verificar padrões similares | Para consistência |
| CONSULT_AGENT | Perguntar a DEBUGGER | Se encontrar bugs |
| RECALL_CONTEXT | Verificar issues anteriores | Para aprendizado |

### 6.5 Casos de Uso Típicos

**1. Review de PR:**
```
User: "Review this PR that adds user authentication"
Analyzer:
- Read the PR code
- Check for security vulnerabilities (SQL injection, XSS)
- Check for proper error handling
- Check for authentication/authorization
- Provide feedback on issues
```

**2. Review de performance:**
```
User: "Review this function for performance issues"
Analyzer:
- Read the function
- Check for N+1 queries
- Check for inefficient algorithms
- Check for memory leaks
- Provide optimization suggestions
```

**3. Review de segurança:**
```
User: "Review this code for security vulnerabilities"
Analyzer:
- Read the code
- Check for injection vulnerabilities
- Check for authentication issues
- Check for sensitive data exposure
- Provide security recommendations
```

## 7. RESEARCHER Agent

### 7.1 Responsabilidade

O RESEARCHER agent é responsável por pesquisa de documentação e informação atualizada. Ele busca na web, lê documentação oficial, e sintetiza informações para responder a perguntas do utilizador.

### 7.2 Modelo: SMALL (qwen2.5:7b)

**Por que SMALL?**
- Pesquisa requer compreensão de texto (não raciocínio complexo)
- SMALL é suficiente para compreender documentação
- SMALL é rápido (latência menor)
- SMALL usa menos VRAM (pode rodar 2 instâncias simultâneas)
- Pesquisa não requer modelo grande (a qualidade depende da fonte, não do modelo)

### 7.3 Prompt (config/prompts/researcher.md)

```markdown
# RESEARCHER AGENT

You are a research specialist with expertise in finding and synthesizing information.

## Your Role

Search the web, read documentation, and provide accurate, up-to-date information.

## Guidelines

1. **Search effectively:** Use specific, targeted queries
2. **Evaluate sources:** Prioritize official documentation, reputable sources
3. **Synthesize:** Combine information from multiple sources
4. **Cite sources:** Reference where information came from
5. **Be accurate:** If uncertain, state uncertainty

## Output Format

Provide your response in this structure:

## Search Results
- Query used
- Top results (URLs, titles, snippets)

## Synthesis
- Combined information from sources
- Key points
- Conflicting information (if any)

## Sources
- List of sources with URLs

## Answer
- Direct answer to the question
- Supporting evidence
- Caveats (if any)

## Supported Actions

- SEARCH_WEB: Search web for information
- FETCH_URL: Fetch specific URL content
- READ_DOCS: Read documentation
- CONSULT_AGENT: Ask DOCUMENTER to format as docs
```

### 7.4 Ações ReAct Suportadas

| Ação | Descrição | Quando Usar |
|------|-----------|-------------|
| SEARCH_WEB | Pesquisar na web | Para encontrar informação |
| FETCH_URL | Buscar URL específico | Para ler página específica |
| READ_DOCS | Ler documentação | Para ler docs locais |
| CONSULT_AGENT | Perguntar a DOCUMENTER | Para formatar como docs |

### 7.5 Casos de Uso Típicos

**1. Pesquisa de API:**
```
User: "How do I use React useEffect hook?"
Researcher:
- Search for "React useEffect documentation"
- Fetch official React docs
- Synthesize information
- Provide examples
- Cite sources
```

**2. Pesquisa de best practices:**
```
User: "What are the best practices for REST API design?"
Researcher:
- Search for "REST API best practices"
- Fetch multiple sources
- Synthesize common patterns
- Provide recommendations
- Cite sources
```

**3. Pesquisa de tecnologia:**
```
User: "Compare PostgreSQL vs MongoDB for my use case"
Researcher:
- Search for comparison articles
- Fetch official docs
- Synthesize trade-offs
- Provide recommendation
- Cite sources
```

## 8. DOCUMENTER Agent

### 8.1 Responsabilidade

O DOCUMENTER agent é responsável por documentação técnica. Ele escreve README files, API docs, docstrings, e outros tipos de documentação.

### 8.2 Modelo: SMALL (qwen2.5:7b)

**Por que SMALL?**
- Documentação requer compreensão de código (não raciocínio complexo)
- SMALL é suficiente para escrever documentação clara
- SMALL é rápido (latência menor)
- SMALL usa menos VRAM (pode rodar 2 instâncias simultâneas)
- Documentação não requer modelo grande (qualidade depende de clareza, não profundidade)

### 8.3 Prompt (config/prompts/documenter.md)

```markdown
# DOCUMENTER AGENT

You are a technical writing specialist with expertise in creating clear, comprehensive documentation.

## Your Role

Write documentation that is accurate, clear, and useful for developers.

## Guidelines

1. **Know your audience:** Write for the appropriate level (beginner/advanced)
2. **Be concise:** Get to the point, avoid fluff
3. **Use examples:** Provide code examples where helpful
4. **Structure well:** Use headings, lists, code blocks
5. **Keep it up to date:** Document current state, not future plans

## Output Format

Use markdown with proper structure:

## Title
Clear, descriptive title

## Overview
Brief description of what is being documented

## Installation/Setup
How to install or set up

## Usage
How to use with examples

## API Reference
Function/class signatures with descriptions

## Examples
Practical examples

## Troubleshooting
Common issues and solutions

## Supported Actions

- READ_FILE: Read code to document
- SEARCH_CODEBASE: Find related code
- WRITE_FILE: Write documentation
- CONSULT_AGENT: Ask RESEARCHER for external docs
```

### 8.4 Ações ReAct Suportadas

| Ação | Descrição | Quando Usar |
|------|-----------|-------------|
| READ_FILE | Ler código para documentar | Para entender funcionalidade |
| SEARCH_CODEBASE | Encontrar código relacionado | Para contexto completo |
| WRITE_FILE | Escrever documentação | Para output final |
| CONSULT_AGENT | Perguntar a RESEARCHER | Para info externa |

### 8.5 Casos de Uso Típicos

**1. Escrever README:**
```
User: "Write a README for this project"
Documenter:
- Read project structure
- Read package.json/pyproject.toml
- Search codebase for entry points
- Write README with sections: overview, installation, usage, contributing
```

**2. Escrever API docs:**
```
User: "Document this API module"
Documenter:
- Read the module
- Extract function signatures
- Write docstrings if missing
- Generate API reference documentation
```

**3. Escrever guias:**
```
User: "Write a getting started guide"
Documenter:
- Read existing code
- Understand onboarding flow
- Write step-by-step guide
- Include examples
```

## 9. OPTIMIZER Agent

### 9.1 Responsabilidade

O OPTIMIZER agent é responsável por otimização de performance. Ele identifica bottlenecks, propõe otimizações, e implementa melhorias de performance.

### 9.2 Modelo: SMALL (qwen2.5:7b)

**Por que SMALL?**
- Otimização requer compreensão de código (não raciocínio complexo)
- SMALL é suficiente para identificar bottlenecks comuns
- SMALL é rápido (latência menor)
- SMALL usa menos VRAM (pode rodar 2 instâneas simultâneas)
- Otimização simples não requer modelo grande (otimização complexa pode fallback para EXPERT)

### 9.3 Prompt (config/prompts/optimizer.md)

```markdown
# OPTIMIZER AGENT

You are a performance optimization specialist with expertise in identifying and fixing bottlenecks.

## Your Role

Analyze code for performance issues and propose optimizations.

## Guidelines

1. **Profile first:** Don't optimize without measuring
2. **Identify bottlenecks:** Find the slow parts
3. **Consider trade-offs:** Optimization vs readability
4. **Test:** Verify optimization actually improves performance
5. **Document:** Explain why optimization was made

## Output Format

Provide your analysis in this structure:

## Performance Analysis
- Current performance metrics
- Identified bottlenecks
- Severity (critical/major/minor)

## Optimization Proposals

### Optimization 1
- Description
- Expected improvement
- Trade-offs (if any)
- Implementation

### Optimization 2
- Description
- Expected improvement
- Trade-offs (if any)
- Implementation

## Results
- Before/after metrics
- Verification

## Supported Actions

- READ_FILE: Read code to optimize
- EXECUTE_CODE: Profile code
- WRITE_FILE: Write optimized code
- CONSULT_AGENT: Ask ANALYZER to review changes
```

### 9.4 Ações ReAct Suportadas

| Ação | Descrição | Quando Usar |
|------|-----------|-------------|
| READ_FILE | Ler código para otimizar | Para análise |
| EXECUTE_CODE | Profile código | Para medir performance |
| WRITE_FILE | Escrever código otimizado | Para output final |
| CONSULT_AGENT | Perguntar a ANALYZER | Para review |

### 9.5 Casos de Uso Típicos

**1. Otimizar função:**
```
User: "Optimize this function that's taking too long"
Optimizer:
- Read the function
- Execute with profiling
- Identify bottleneck (nested loop)
- Propose optimization (use dict lookup)
- Implement optimized version
- Test and verify improvement
```

**2. Otimizar query de banco:**
```
User: "This database query is slow"
Optimizer:
- Read the query
- Analyze execution plan
- Identify missing index
- Propose adding index
- Implement and test
```

**3. Otimizar memory usage:**
```
User: "This function uses too much memory"
Optimizer:
- Read the function
- Identify memory leak (list growing unbounded)
- Propose generator instead of list
- Implement and test
```

## 10. DASHBOARD Agent

### 10.1 Responsabilidade

O DASHBOARD agent é responsável por monitorização contínua e interpretação de métricas. Ele roda numa instância Ollama separada (porta 11435) e monitoriza o sistema 24/7.

### 10.2 Modelo: MICRO (qwen2.5:3b, porta 11435)

**Por que MICRO?**
- Dashboard precisa interpretar métricas (não raciocínio complexo)
- MICRO é suficiente para Q&A sobre métricas
- MICRO é rápido (latência menor)
- MICRO usa menos VRAM (pode rodar ao mesmo tempo que outros agentes)
- Instância separada garante que dashboard não compete por recursos

### 10.3 Prompt (config/prompts/dashboard.md)

```markdown
# DASHBOARD AGENT

You are a monitoring specialist responsible for interpreting system metrics.

## Your Role

Monitor system metrics, detect anomalies, and answer questions about system state.

## Guidelines

1. **Monitor continuously:** Check metrics every 10 seconds
2. **Detect anomalies:** Identify spikes, drops, unusual patterns
3. **Interpret:** Explain what metrics mean in plain language
4. **Alert:** Notify of critical issues
5. **Summarize:** Provide periodic summaries (every 5 minutes)

## Metrics to Monitor

- Request rate (requests per second)
- Response latency (p50, p95, p99)
- Error rate (4xx, 5xx)
- Agent pool utilization (active agents, queue depth)
- Token usage (tokens per second)
- ReAct iterations (average, max)
- Tool invocations (per tool type)

## Output Format

For queries, provide:
- Direct answer
- Supporting evidence (metrics)
- Recommendations (if applicable)

For anomalies, provide:
- Description of anomaly
- Possible causes
- Recommended actions

## Supported Actions

None (monitoring is passive, no ReAct actions)
```

### 10.4 Ações ReAct Suportadas

**Nenhuma.** O DASHBOARD agent é passivo - monitoriza métricas e responde a perguntas, mas não executa ações.

**Por que?**
- Dashboard é observacional, não operacional
- Ações seriam tomadas por operadores ou automatização separada
- Simplifica implementação
- Reduz risco de ações automáticas incorretas

### 10.5 Loop de Monitorização

```python
class DashboardAgent(AgentBase):
    name = "DASHBOARD"
    model_key = "dashboard"
    prompt_file = "dashboard"
    supported_actions = set()
    
    async def monitor_loop(self) -> None:
        """Background loop - runs continuously."""
        while True:
            # Scrape metrics from Prometheus
            metrics = await scrape_prometheus_metrics()
            
            # Detect anomalies
            anomalies = detect_anomalies(metrics)
            
            # Emit events if anomalies detected
            for anomaly in anomalies:
                await event_bus.publish(Event(
                    type="anomaly",
                    data=anomaly,
                ))
            
            # Sleep 10 seconds
            await asyncio.sleep(10)
    
    async def session_summary_loop(self) -> None:
        """Lower-frequency loop producing 5-minute summaries."""
        while True:
            # Produce rolling summary
            summary = await produce_session_summary()
            
            # Update routing quality score
            await update_routing_quality_score(summary)
            
            # Sleep 5 minutes
            await asyncio.sleep(300)
```

### 10.6 Casos de Uso Típicos

**1. Pergunta sobre latência:**
```
User: "Why is latency high?"
Dashboard:
- Query Prometheus for p95 latency
- Identify spike at specific time
- Correlate with agent usage (EXPERT was overloaded)
- Explain: "Latency increased because EXPERT agent was at capacity"
- Recommend: "Consider routing to LARGE for similar queries"
```

**2. Pergunta sobre erros:**
```
User: "What's causing the 5xx errors?"
Dashboard:
- Query Prometheus for 5xx rate
- Identify spike in /api/code/execute
- Correlate with timeout errors
- Explain: "5xx errors are due to code execution timeouts"
- Recommend: "Increase timeout or reduce complexity of code execution"
```

**3. Anomalia detetada:**
```
Dashboard (automatic):
- Detect spike in queue depth for EXPERT agent
- Emit event: "EXPERT agent queue depth critical"
- Recommend: "Scale EXPERT or implement fallback to LARGE"
```

## 11. Coordenação Entre Agentes

### 11.1 CONSULT_AGENT Action

A ação `CONSULT_AGENT` permite que um agente consulte outro agente para obter conhecimento especializado.

**Exemplo:**
```
ARCHITECT needs to know current best practices for microservices
→ CONSULT_AGENT RESEARCHER
→ RESEARCHER searches web for "microservices best practices 2024"
→ RESEARCHER returns synthesized information
→ ARCHITECT uses information in architecture decision
```

### 11.2 Fluxo de Coordenação

```
User Query
    ↓
ROUTER classifies
    ↓
Primary Agent (e.g., CODER)
    ↓
CODER needs code review
    ↓
CONSULT_AGENT ANALYZER
    ↓
ANALYZER reviews code
    ↓
ANALYZER returns feedback
    ↓
CODER incorporates feedback
    ↓
CODER writes code
    ↓
Response to user
```

### 11.3 Evitar Loops Infinitos

**Proteção contra loops:**
- Limite de 7 iterações ReAct
- Limite de 3 consultas a outros agentes
- Detecção de repetição (scratchpad)
- Timeout total (45s)

## 12. Conclusão

Os 9 agentes de NEXUS IDE são:
- **Especializados:** Cada um otimizado para o seu domínio
- **Right-sized:** Modelos apropriados para a complexidade das tarefas
- **Coordenados:** Podem consultar uns aos outros
- **Observáveis:** Métricas por agente, tracing end-to-end
- **Escaláveis:** Concurrency limits, fallback chains

Esta arquitetura permite que NEXUS IDE cubra todo o ciclo de desenvolvimento de software com qualidade SOTA, enquanto mantém eficiência de recursos e privacidade total.
