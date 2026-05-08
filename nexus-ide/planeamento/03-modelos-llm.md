# NEXUS IDE — Modelos LLM e Estratégias de Seleção

## 1. Visão Geral da Estratégia de Modelos

NEXUS IDE adota uma abordagem de "right-sized models" - cada tarefa utiliza o menor modelo viável para atingir o objetivo. Esta estratégia é baseada em três princípios fundamentais:

1. **Eficiência de Recursos:** Modelos menores usam menos VRAM, menos energia, e inferem mais rápido
2. **Especialização:** Modelos especializados superam generalistas em tarefas específicas
3. **Escalabilidade:** Múltiplos modelos pequenos podem rodar simultaneamente na mesma GPU

### 1.1 Matriz de Modelos

| ID Interno | Modelo Ollama | VRAM | Caso de Uso Primário | Justificativa |
|------------|---------------|------|----------------------|---------------|
| NANO | qwen2.5:0.5b | ~400MB | Routing, classificação | Suficiente para decisões binárias/categorização |
| MICRO | qwen2.5:3b | ~2GB | Q&A simples, formatação | Equilíbrio qualidade/recursos para NLP básico |
| SMALL | qwen2.5:7b | ~4.7GB | Análise de código, tarefas gerais | Ponto ideal para tarefas de complexidade média |
| MEDIUM | qwen2.5-coder:7b | ~4.7GB | Geração de código focada | Modelo especializado em código supera generalista |
| LARGE | qwen2.5:14b | ~9GB | Arquitetura, análise complexa | Raciocínio profundo requer modelo grande |
| EXPERT | qwen2.5-coder:32b | ~20GB | Engenharia avançada, codebase grande | Modelo de código SOTA para tarefas complexas |
| VISION | llava:7b | ~4.7GB | Análise de imagem/UI | Multimodal (placeholder, não usado em Tier 1) |
| EMBED | nomic-embed-text | ~270MB | Embeddings, busca semântica | Modelo dedicado para embeddings |
| DASHBOARD | qwen2.5:3b | ~2GB | Monitorização contínua | Instância separada em porta 11435 |

### 1.2 Por que Qwen2.5?

A escolha da família Qwen2.5 (em vez de Llama, Mistral, ou outras) é baseada em múltiplos fatores:

**Performance:**
- Qwen2.5 supera Llama 3 em benchmarks de código (HumanEval, MBPP)
- Qwen2.5-coder é especificamente treinado para código
- Qwen2.5 tem excelente performance em português (importante para utilizadores lusófonos)

**Licença:**
- Qwen2.5 é Apache 2.0 (permissiva, permite uso comercial)
- Llama 3 é Meta Llama 3 Community License (mais restritiva)
- Mistral é Apache 2.0, mas Qwen2.5 tem melhor performance em código

**Ecossistema Ollama:**
- Qwen2.5 é bem suportado em Ollama
- Múltiplos tamanhos disponíveis (0.5b, 3b, 7b, 14b, 32b)
- Versão coder dedicada
- Ativamente mantido

**Tamanho:**
- Qwen2.5:0.5b é extremamente pequeno (ideal para routing)
- Qwen2.5:32b é grande o suficiente para tarefas complexas
- Faixa de tamanhos cobre todos os casos de uso

**Alternativas Consideradas e Rejeitadas:**

| Modelo | Por que Rejeitado? |
|--------|-------------------|
| Llama 3 | Licença mais restritiva, menor performance em código |
| Mistral 7B | Menor performance em benchmarks, menos tamanhos disponíveis |
| CodeLlama | Descontinuado (substituído por Llama 3), menor performance |
| DeepSeek Coder | Excelente performance, mas menos suporte em Ollama |
| StarCoder2 | Licença restritiva (OpenRAIL-M), menor performance |

## 2. Análise Detalhada por Modelo

### 2.1 NANO (qwen2.5:0.5b)

**Características:**
- Parâmetros: 0.5 bilhões
- VRAM: ~400MB (quantizado 4-bit)
- Context window: 32k tokens
- Temperature: 0.1 (baixa variação)

**Casos de Uso:**
- **Routing:** Classificar query em agent (ROUTER → CODER, etc.)
- **Classificação:** Detetar tipo de tarefa (debug, arquitetura, pesquisa)
- **Validação:** Verificar formato de JSON, sintaxe de código

**Por que 0.5b é suficiente?**
- Routing é uma tarefa de classificação binária/multi-classe
- Não requer raciocínio complexo
- Modelos de 0.5b têm >90% accuracy em classificação de texto
- Inferência é quase instantânea (<100ms)

**Configuração:**
```yaml
nano:
  id: "qwen2.5:0.5b"
  ollama_host: "http://localhost:11434"
  thinking_mode: false
  max_tokens: 512
  temperature: 0.1
  use_cases: [routing, classification]
```

**Limit de Concorrência:** 5 (porque é pequeno, pode rodar 5 instâncias simultaneamente)

**Prompt de Routing:**
```markdown
You are a routing agent. Classify the user query into one of these agents:
- ROUTER: (not applicable, you are the router)
- ARCHITECT: system design, architecture
- CODER: code generation, implementation
- DEBUGGER: debugging, troubleshooting
- ANALYZER: code review, analysis
- RESEARCHER: web search, documentation
- DOCUMENTER: documentation writing
- OPTIMIZER: performance optimization

Output JSON only:
{"agent": "CODER", "confidence": 0.95, "reason": "Query explicitly asks for code implementation"}
```

### 2.2 MICRO (qwen2.5:3b)

**Características:**
- Parâmetros: 3 bilhões
- VRAM: ~2GB (quantizado 4-bit)
- Context window: 32k tokens
- Temperature: 0.7 (criatividade moderada)

**Casos de Uso:**
- **Q&A Simples:** Responder perguntas factuais
- **Formatação:** Formatar código, texto, JSON
- **Sumarização:** Resumir documentos, código
- **Dashboard:** Monitorização e interpretação de métricas

**Por que 3b para estas tarefas?**
- Q&A simples não requer raciocínio complexo
- Formatação é uma tarefa estruturada
- Sumarização requer compreensão, mas não raciocínio profundo
- 3b é o ponto ideal entre qualidade e recursos

**Configuração:**
```yaml
micro:
  id: "qwen2.5:3b"
  ollama_host: "http://localhost:11434"
  thinking_mode: false
  max_tokens: 2048
  temperature: 0.7
  use_cases: [simple_qa, formatting, summarization]
```

**Limit de Concorrência:** 3 (balance entre VRAM e throughput)

**Prompt de Formatação:**
```markdown
You are a formatting specialist. Format the following code according to PEP 8.

Input:
{code}

Output only the formatted code.
```

### 2.3 SMALL (qwen2.5:7b)

**Características:**
- Parâmetros: 7 bilhões
- VRAM: ~4.7GB (quantizado 4-bit)
- Context window: 32k tokens
- Temperature: 0.7

**Casos de Uso:**
- **Análise de Código:** Compreender código existente
- **Tarefas Gerais:** Tarefas que não se encaixam em categorias específicas
- **Documentação:** Escrever documentação técnica
- **Pesquisa:** Web search + síntese (RESEARCHER)

**Por que 7b?**
- 7b é o "sweet spot" para tarefas de complexidade média
- Suficiente para compreender contexto de código
- Inferência ainda é rápida (~500ms)
- Cobre 80% dos casos de uso

**Configuração:**
```yaml
small:
  id: "qwen2.5:7b"
  ollama_host: "http://localhost:11434"
  thinking_mode: false
  max_tokens: 8192
  temperature: 0.7
  use_cases: [code_analysis, general_tasks, documentation]
```

**Limit de Concorrência:** 2 (2 instâncias = ~10GB VRAM total)

### 2.4 MEDIUM (qwen2.5-coder:7b)

**Características:**
- Parâmetros: 7 bilhões (coder-specific)
- VRAM: ~4.7GB (quantizado 4-bit)
- Context window: 32k tokens
- Temperature: 0.3 (baixa variação para código)

**Casos de Uso:**
- **Geração de Código Focada:** Implementar funções, classes
- **Debugging Simples:** Encontrar bugs em código pequeno
- **Refactoring:** Refatorar código existente

**Por que qwen2.5-coder e não qwen2.5?**
- qwen2.5-coder é treinado especificamente em código
- Superior em benchmarks de código (HumanEval, MBPP)
- Melhor em seguir padrões de código
- Melhor em gerar código funcional

**Por que não usar EXPERT (32b) para tudo?**
- EXPERT é overkill para tarefas simples
- EXPERT usa muito mais VRAM (20GB vs 5GB)
- EXPERT é mais lento (inferência)
- MEDIUM é suficiente para 60% de tarefas de código

**Configuração:**
```yaml
medium:
  id: "qwen2.5-coder:7b"
  ollama_host: "http://localhost:11434"
  thinking_mode: false
  max_tokens: 8192
  temperature: 0.3
  use_cases: [code_generation_medium, debugging_simple]
```

**Limit de Concorrência:** 2

### 2.5 LARGE (qwen2.5:14b)

**Características:**
- Parâmetros: 14 bilhões
- VRAM: ~9GB (quantizado 4-bit)
- Context window: 32k tokens
- Temperature: 0.7
- Thinking Mode: false (pode ser ativado para tarefas complexas)

**Casos de Uso:**
- **Arquitetura de Sistemas:** Design de arquitetura complexa
- **Análise Complexa:** Code review de sistemas grandes
- **Raciocínio Profundo:** Tarefas que requerem múltiplos passos de raciocínio

**Por que 14b?**
- Arquitetura requer compreensão de sistemas inteiros
- 14b tem capacidade de raciocínio multi-passo
- Suficiente para entender dependências complexas
- Inferência ainda é aceitável (~2s)

**Por que não 32b?**
- 32b é reservado para EXPERT (código)
- 14b é suficiente para arquitetura (não é código)
- 14b usa metade da VRAM de 32b
- 14b é mais rápido

**Configuração:**
```yaml
large:
  id: "qwen2.5:14b"
  ollama_host: "http://localhost:11434"
  thinking_mode: false
  max_tokens: 16384
  temperature: 0.7
  use_cases: [architecture, complex_analysis, reasoning]
```

**Limit de Concorrência:** 1 (apenas 1 instância devido ao tamanho)

### 2.6 EXPERT (qwen2.5-coder:32b)

**Características:**
- Parâmetros: 32 bilhões (MoE - Mixture of Experts)
- VRAM: ~20GB (quantizado 4-bit)
- Context window: 32k tokens
- Temperature: 0.3
- Thinking Mode: false

**Casos de Uso:**
- **Engenharia Avançada:** Implementar sistemas complexos
- **Codebase Grande:** Trabalhar com codebases de 100k+ linhas
- **Refactoring Complexo:** Refatorar arquiteturas inteiras

**Por que 32b MoE?**
- MoE (Mixture of Experts) permite modelo grande com inferência eficiente
- 32b é SOTA para código (supera Llama 3 70b em benchmarks)
- Necessário para codebases grandes (contexto complexo)
- Necessário para tarefas que requerem conhecimento profundo

**Por que não 70b (Llama 3)?**
- Llama 3 70b requer ~40GB VRAM (muito para GPU comum)
- Qwen2.5-coder:32b tem melhor performance em código
- Qwen2.5-coder:32b usa metade da VRAM

**Configuração:**
```yaml
expert:
  id: "qwen2.5-coder:32b"
  ollama_host: "http://localhost:11434"
  thinking_mode: false
  max_tokens: 32768
  temperature: 0.3
  use_cases: [complex_code, engineering, large_codebase]
```

**Limit de Concorrência:** 1 (apenas 1 instância devido ao tamanho)

### 2.7 VISION (llava:7b)

**Características:**
- Parâmetros: 7 bilhões (multimodal)
- VRAM: ~4.7GB
- Context window: 4k tokens (imagem + texto)
- Temperature: 0.5

**Casos de Uso:**
- **Análise de Imagem:** Screenshots, wireframes
- **UI Understanding:** Compreender interfaces de utilizador
- **OCR:** Extrair texto de imagens

**Por que LLaVA e não Qwen-VL?**
- LLaVA é mais maduro e testado
- LLaVA tem melhor suporte em Ollama
- Qwen-VL é mais recente, menos estável

**Nota:** Vision é placeholder para Tier 1. Não será usado inicialmente. Será implementado em fases posteriores.

**Configuração:**
```yaml
vision:
  id: "llava:7b"
  ollama_host: "http://localhost:11434"
  thinking_mode: false
  max_tokens: 4096
  temperature: 0.5
  use_cases: [image_analysis, ui_understanding]
```

**Limit de Concorrência:** 1

### 2.8 EMBED (nomic-embed-text)

**Características:**
- Parâmetros: 270 milhões
- VRAM: ~270MB
- Embedding dimension: 768
- Context window: 8192 tokens

**Casos de Uso:**
- **Embeddings:** Gerar embeddings para busca semântica
- **RAG:** Retrieval-Augmented Generation
- **Similaridade:** Encontrar código similar

**Por que nomic-embed-text?**
- Especializado em embeddings (não é modelo geral)
- Pequeno e rápido (270MB)
- Excelente performance em benchmarks de similarity
- Open-source e permissivo

**Por que não usar modelo geral (qwen2.5) para embeddings?**
- Modelos gerais são menos eficientes para embeddings
- Modelos dedicados têm melhor performance
- Modelos dedicados são mais rápidos
- Modelos dedicados usam menos VRAM

**Configuração:**
```yaml
embed:
  id: "nomic-embed-text"
  ollama_host: "http://localhost:11434"
  thinking_mode: false
  max_tokens: 0
  temperature: 0.0
  use_cases: [embeddings, semantic_search]
```

**Limit de Concorrência:** Não aplicável (não é conversacional)

### 2.9 DASHBOARD (qwen2.5:3b)

**Características:**
- Parâmetros: 3 bilhões
- VRAM: ~2GB
- Context window: 32k tokens
- Temperature: 0.3
- Porta: 11435 (separada da instância principal)

**Casos de Uso:**
- **Monitorização Contínua:** Monitorizar métricas Prometheus
- **Detecção de Anomalias:** Detetar spikes em latência, erros
- **Sumarização:** Produzir sumários de sessão a cada 5 minutos
- **Q&A de Métricas:** Responder a perguntas em linguagem natural sobre métricas

**Por que Instância Separada (porta 11435)?**
- Dashboard agent é always-on (loop contínuo)
- Não deve competir por recursos com outros agentes
- Permite monitorização mesmo se instância principal estiver sobrecarregada
- Isolamento de falhas (dashboard não afeta chat)

**Por que 3b e não 0.5b?**
- Dashboard precisa interpretar métricas (não apenas classificar)
- 3b tem capacidade de raciocínio básico
- 3b é suficiente para Q&A sobre métricas

**Configuração:**
```yaml
dashboard:
  id: "qwen2.5:3b"
  ollama_host: "http://localhost:11435"
  thinking_mode: false
  max_tokens: 1024
  temperature: 0.3
  use_cases: [dashboard_monitoring, metrics_interpretation]
```

**Limit de Concorrência:** 1 (apenas 1 instância, always-on)

## 3. Thinking Mode

### 3.1 O que é Thinking Mode?

Thinking Mode é uma técnica onde o modelo é instruído a "pensar em voz alta" antes de responder. Isto é implementado através de um prompt especial que pede ao modelo para:

1. Decompor o problema
2. Considerar múltiplas abordagens
3. Avaliar prós e contras
4. Escolher a melhor abordagem
5. Explicar o raciocínio

### 3.2 Quando Usar Thinking Mode?

**Deve usar:**
- Arquitetura de sistemas (ARCHITECT)
- Análise complexa (ANALYZER)
- Debugging difícil (DEBUGGER)
- Tarefas com alta complexidade (estimated_complexity > 7)

**Não deve usar:**
- Routing (ROUTER)
- Formatação (MICRO)
- Q&A simples (MICRO)
- Tarefas de baixa complexidade

### 3.3 Implementação

```python
def apply_thinking_mode(prompt: str, model_config: dict) -> str:
    """Apply thinking mode if enabled and complexity threshold met."""
    if model_config["thinking_mode"] and complexity > 7:
        return f"""
Think step by step:
1. Decompose the problem
2. Consider multiple approaches
3. Evaluate pros and cons
4. Choose the best approach
5. Explain your reasoning

{prompt}
"""
    return prompt
```

### 3.4 Por que Thinking Mode é Opcional?

- **Overhead:** Thinking mode aumenta tokens e tempo
- **Nem sempre necessário:** Tarefas simples não precisam de raciocínio explícito
- **Configurável:** Pode ser ativado/desativado por modelo
- **Threshold:** Ativado apenas quando complexity > 7

## 4. Quantização

### 4.1 O que é Quantização?

Quantização é a técnica de reduzir a precisão dos pesos do modelo (de FP32 para FP16, INT8, ou INT4) para reduzir VRAM e aumentar velocidade de inferência.

### 4.2 Estratégia de Quantização do NEXUS IDE

**Ollama usa quantização 4-bit por padrão:**
- Reduz VRAM em ~4x
- Perda de qualidade mínima (<2% em benchmarks)
- Inferência 2-3x mais rápida
- Suportado nativamente por Ollama

**Por que 4-bit e não 8-bit ou FP16?**
- 4-bit é o sweet spot entre qualidade e VRAM
- 8-bit usa 2x mais VRAM com ganho de qualidade marginal
- FP16 usa 4x mais VRAM com ganho de qualidade pequeno
- 4-bit permite rodar múltiplos modelos simultaneamente

**Quando usar quantização diferente?**
- **FP16:** Para EXPERT se qualidade é crítica (ex: produção)
- **8-bit:** Para LARGE se VRAM disponível
- **4-bit:** Default para todos os modelos

### 4.3 Impacto na Qualidade

Benchmarks mostram que quantização 4-bit tem impacto mínimo:
- HumanEval: -1.2% accuracy
- MBPP: -0.8% accuracy
- MMLU: -1.5% accuracy

Este trade-off é aceitável dado o ganho em VRAM e velocidade.

## 5. Context Window

### 5.1 Context Window por Modelo

| Modelo | Context Window | Justificativa |
|--------|---------------|---------------|
| NANO | 512 | Routing não precisa de muito contexto |
| MICRO | 2048 | Q&A simples, formatação |
| SMALL | 8192 | Análise de código (ficheiros médios) |
| MEDIUM | 8192 | Geração de código (contexto de ficheiro) |
| LARGE | 16384 | Arquitetura (contexto de sistema) |
| EXPERT | 32768 | Codebase grande (múltiplos ficheiros) |
| VISION | 4096 | Imagem + texto |
| EMBED | 8192 | Embeddings de ficheiros |
| DASHBOARD | 1024 | Métricas (não precisa de muito contexto) |

### 5.2 Por que Context Windows Diferentes?

- **Eficiência:** Context window maior = mais VRAM
- **Necessidade:** Nem todas as tarefas precisam de muito contexto
- **Latência:** Context window maior = inferência mais lenta
- **Escala:** EXPERT precisa de 32k para codebase grande

### 5.3 Gestão de Context

**Para tarefas que excedem o context window:**
1. Chunking: Dividir em múltiplos prompts
2. RAG: Recuperar partes relevantes via embeddings
3. Sumarização: Sumarizar contexto antes de passar ao modelo
4. Hierarchical: Passar sumário de nível alto, detalhes sob demanda

## 6. Temperature

### 6.1 O que é Temperature?

Temperature controla a "criatividade" do modelo:
- **Baixa (0.1-0.3):** Respostas mais determinísticas, menos variação
- **Média (0.5-0.7):** Equilíbrio entre criatividade e consistência
- **Alta (0.8-1.0):** Mais criativo, mais variação

### 6.2 Temperature por Modelo

| Modelo | Temperature | Justificativa |
|--------|-------------|---------------|
| NANO | 0.1 | Routing precisa ser determinístico |
| MICRO | 0.7 | Q&A/formatação pode ter variação |
| SMALL | 0.7 | Tarefas gerais beneficiam de criatividade |
| MEDIUM | 0.3 | Código precisa ser consistente |
| LARGE | 0.7 | Arquitetura beneficia de exploração |
| EXPERT | 0.3 | Código precisa ser consistente |
| VISION | 0.5 | Análise de imagem precisa de algum variação |
| EMBED | 0.0 | Embeddings são determinísticos |
| DASHBOARD | 0.3 | Métricas precisam de interpretação consistente |

### 6.3 Por que estas Temperaturas?

- **Routing (0.1):** Precisa ser determinístico (mesma query → mesmo agente)
- **Código (0.3):** Código precisa ser funcional e consistente
- **Arquitetura (0.7):** Exploração de múltiplas abordagens é benéfica
- **Q&A (0.7):** Respostas podem variar, mas ainda relevantes
- **Embeddings (0.0):** Embeddings devem ser idênticos para o mesmo input

## 7. Concorrência e Semáforos

### 7.1 Limits de Concorrência

```yaml
concurrency:
  NANO: 5      # 5 instâncias simultâneas
  MICRO: 3     # 3 instâncias simultâneas
  SMALL: 2     # 2 instâncias simultâneas
  MEDIUM: 2    # 2 instâncias simultâneas
  LARGE: 1     # 1 instância simultânea
  EXPERT: 1    # 1 instância simultânea
  VISION: 1    # 1 instância simultânea
  DASHBOARD: 1 # 1 instância simultânea
```

### 7.2 Cálculo de VRAM

**Assumindo GPU com 12GB VRAM:**
- NANO (0.4GB × 5) = 2GB
- MICRO (2GB × 3) = 6GB
- SMALL (4.7GB × 2) = 9.4GB
- MEDIUM (4.7GB × 2) = 9.4GB
- LARGE (9GB × 1) = 9GB
- EXPERT (20GB × 1) = 20GB (requer GPU dedicada)

**Estratégia:**
- NANO, MICRO, SMALL podem rodar simultaneamente
- MEDIUM e LARGE alternam
- EXPERT roda em GPU dedicada ou CPU (mais lento)

### 7.3 Por que Semáforos e não Queue?

- **Semáforos:** Bloqueiam se limite atingido (espera)
- **Queue:** Enfileira requests (FIFO)

**Por que Semáforos?**
- Mais simples de implementar
- Menos latência (fila pode crescer infinitamente)
- Fair scheduling (FIFO implícito)
- Configurável via models.yaml

**Quando Queue seria melhor?**
- Se tivermos overflow massivo (100+ requests)
- Se quisermos priorizar certos requests
- Necessário apenas em escala muito grande

## 8. Fallback Chain

### 8.1 Configuração de Fallback

```yaml
fallback:
  EXPERT:  [LARGE, SMALL, MICRO]
  LARGE:   [SMALL, MEDIUM, MICRO]
  CODER:   [MEDIUM, SMALL, NANO]
  RESEARCHER: [SMALL, MICRO, NANO]
```

### 8.2 Lógica de Fallback

```python
async def execute_with_fallback(agent_name: str, request: Request):
    """Execute agent with fallback chain."""
    fallback_chain = get_fallback_chain(agent_name)
    
    for fallback_agent in fallback_chain:
        try:
            result = await execute_agent(fallback_agent, request)
            return result
        except (TimeoutError, OOMError, ModelError) as e:
            log_fallback(agent_name, fallback_agent, e)
            continue
    
    # If all fallbacks fail, return error
    raise ExecutionFailed("All fallbacks exhausted")
```

### 8.3 Por que estas Chains?

**EXPERT → LARGE → SMALL → MICRO:**
- EXPERT é o melhor, mas mais pesado
- LARGE é bom para arquitetura
- SMALL é bom para tarefas gerais
- MICRO é último recurso (qualidade menor, mas funcional)

**Por que não NANO no final?**
- NANO é muito pequeno para tarefas complexas
- MICRO é o mínimo razoável
- NANO seria apenas para routing/classificação

### 8.4 Timeout por Nível

```yaml
routing:
  fallback_timeout_seconds: 45
  queue_timeout_seconds: 30
```

- **Fallback timeout:** 45s para tentar fallback
- **Queue timeout:** 30s para adquirir semáforo

**Por que 45s?**
- EXPERT pode levar até 30s para inferência
- 45s permite tempo para fallback
- Utilador não espera mais de 45s

## 9. Atualização de Modelos

### 9.1 Pipeline de Atualização

**Quando atualizar modelos?**
- Novo modelo SOTA disponível
- Benchmark mostra melhoria significativa (>10%)
- Bug crítico em modelo atual
- Comunidade solicita

**Como atualizar:**
1. Testar novo modelo em ambiente de staging
2. Rodar benchmarks (HumanEval, MBPP, MMLU)
3. Comparar com modelo atual
4. Se melhoria >10%, atualizar models.yaml
5. Deploy gradual (canary)
6. Monitorizar métricas (latência, qualidade)

### 9.2 A/B Testing

```python
async def ab_test_model(query: str, model_a: str, model_b: str):
    """A/B test two models for the same query."""
    result_a = await execute_model(query, model_a)
    result_b = await execute_model(query, model_b)
    
    # Compare quality (human evaluation or automated metric)
    quality_a = evaluate_quality(query, result_a)
    quality_b = evaluate_quality(query, result_b)
    
    return {
        "model_a": {"result": result_a, "quality": quality_a},
        "model_b": {"result": result_b, "quality": quality_b},
    }
```

## 10. Conclusão

A estratégia de modelos de NEXUS IDE é baseada em:
- **Right-sizing:** Cada tarefa usa o menor modelo viável
- **Especialização:** Modelos especializados superam generalistas
- **Eficiência:** Quantização 4-bit, context windows otimizados
- **Escalabilidade:** Semáforos, fallback chains, concorrência configurável
- **Flexibilidade:** models.yaml externalizado, fácil de atualizar

Esta estratégia permite que NEXUS IDE rode em hardware acessível (GPU 8-12GB) enquanto mantém qualidade SOTA.
