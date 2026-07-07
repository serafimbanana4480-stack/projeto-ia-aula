# Prompt de Auditoria Completa e Profissional - Projeto Nexus IDE

## Objetivo
Realizar uma auditoria técnica completa, profissional e autônoma do projeto Nexus IDE, incluindo análise de código, testes de funcionalidades, verificação de dashboard, execução de ferramentas e geração de relatório detalhado com recomendações de melhorias.

## Contexto do Projeto
O Nexus IDE é um projeto localizado em `projeto-ia-aula/nexus-ide/` que aparenta ser uma IDE (Integrated Development Environment) com componentes de frontend, backend, agentes de IA, e ferramentas de observabilidade.

## Escopo da Auditoria

### 1. Análise Arquitetural
- Examine a estrutura de diretórios e organização do projeto
- Identifique os principais componentes: backend, frontend, agentes, ferramentas
- Mapeie as dependências entre módulos
- Avalie a escalabilidade e manutenibilidade da arquitetura
- Verifique padrões de design aplicados

### 2. Análise de Código
**Backend:**
- Revise routers, controllers e endpoints da API
- Analise implementação de agentes e ferramentas
- Verifique tratamento de erros e validações
- Examine segurança (autenticação, autorização, sanitização)
- Avalie performance e otimizações

**Frontend:**
- Analise componentes React/Vue e sua estrutura
- Verifique gerenciamento de estado
- Avalie UX/UI e acessibilidade
- Examine integração com API backend
- Verifique responsividade e performance

**Infraestrutura:**
- Revise configurações de ambiente (.env)
- Analise setup de banco de dados
- Verifique configurações de deployment
- Examine logs e sistema de backup

### 3. Testes e Execução
**Testes Funcionais:**
- Execute todos os testes unitários existentes
- Execute testes de integração
- Identifique gaps de cobertura de testes
- Teste fluxos críticos end-to-end

**Execução Prática:**
- Inicialize o backend e verifique funcionamento
- Inicialize o frontend e teste interface
- Execute ferramentas CLI disponíveis
- Teste integração entre componentes

### 4. Dashboard e Interface Web
**Verificação Profunda:**
- Acesse e navegue pela dashboard completa
- Teste todos os botões, formulários e interações
- Verifique carregamento de dados e APIs
- Teste funcionalidades de editor de código
- Avalie visualizações e gráficos
- Verifique responsividade em diferentes resoluções
- Teste em diferentes navegadores (se possível)

### 5. Ferramentas e Utilitários
- Execute cada tool/utilitário disponível
- Verifique funcionamento de comandos CLI
- Teste integração com LLMs (AirLLM, Ollama)
- Avalie ferramentas de observabilidade
- Teste sistema de backup e logs

### 6. Qualidade e Boas Práticas
- Verifique aderência a padrões de código
- Analise documentação inline (comentários)
- Avalie legibilidade e manutenibilidade
- Identifique code smells e anti-patterns
- Verifique uso de tipos (TypeScript, type hints Python)

### 7. Segurança
- Analise vulnerabilidades conhecidas em dependências
- Verifique exposição de dados sensíveis
- Avalie implementação de autenticação/autorização
- Examine validação de inputs
- Verifique configurações de CORS e CSP

### 8. Performance
- Identifique gargalos de performance
- Avalie tempo de resposta de APIs
- Verifique otimizações de queries
- Analise carregamento de assets frontend
- Examine uso de cache

### 9. Documentação
- Avalie README e documentação do projeto
- Verifique instruções de setup e instalação
- Analise documentação de APIs
- Examine guias de contribuição
- Verifique documentação de arquitetura

## Formato do Relatório

### Estrutura Esperada:

```markdown
# RELATÓRIO DE AUDITORIA COMPLETA - NEXUS IDE
**Data:** [DATA]
**Auditor:** [IA/Sistema]
**Versão do Projeto:** [VERSÃO]

## 1. SUMÁRIO EXECUTIVO
- Pontuação Geral: X/10
- Status do Projeto: [Produção Ready / Em Desenvolvimento / Crítico]
- Principais Descobertas (Top 5)
- Recomendações Prioritárias (Top 3)

## 2. ANÁLISE ARQUITETURAL
### 2.1 Estrutura do Projeto
- Diagrama de componentes
- Análise de organização
- Avaliação: X/10

### 2.2 Padrões e Design
- Padrões identificados
- Pontos fortes
- Pontos fracos
- Avaliação: X/10

## 3. ANÁLISE DE CÓDIGO
### 3.1 Backend
- Qualidade: X/10
- Principais issues encontrados
- Boas práticas identificadas
- Recomendações específicas

### 3.2 Frontend
- Qualidade: X/10
- Principais issues encontrados
- Boas práticas identificadas
- Recomendações específicas

### 3.3 Infraestrutura
- Qualidade: X/10
- Configurações analisadas
- Problemas identificados
- Recomendações específicas

## 4. TESTES E EXECUÇÃO
### 4.1 Resultados de Testes
- Testes executados: X
- Testes passados: X
- Testes falhos: X
- Cobertura: X%

### 4.2 Execução Prática
- Backend: [Status]
- Frontend: [Status]
- Tools: [Status]
- Problemas encontrados

## 5. DASHBOARD E INTERFACE
### 5.1 Análise de Funcionalidades
- Funcionalidades testadas: [Lista]
- Funcionalidades funcionando: X/Y
- Bugs encontrados: [Lista detalhada]

### 5.2 UX/UI
- Avaliação de usabilidade: X/10
- Problemas de interface
- Sugestões de melhorias

### 5.3 Performance Frontend
- Tempo de carregamento: Xms
- Otimizações necessárias

## 6. FERRAMENTAS E UTILITÁRIOS
### 6.1 Tools CLI
- [Tool 1]: [Status e observações]
- [Tool 2]: [Status e observações]
- ...

### 6.2 Integrações
- LLM: [Status]
- Database: [Status]
- APIs externas: [Status]

## 7. QUALIDADE E BOAS PRÁTICAS
- Code Quality Score: X/10
- Principais code smells
- Violações de padrões
- Recomendações

## 8. SEGURANÇA
- Security Score: X/10
- Vulnerabilidades críticas: X
- Vulnerabilidades médias: X
- Vulnerabilidades baixas: X
- Ações imediatas necessárias

## 9. PERFORMANCE
- Performance Score: X/10
- Gargalos identificados
- Otimizações sugeridas
- Impacto estimado

## 10. DOCUMENTAÇÃO
- Documentation Score: X/10
- Gaps de documentação
- Melhorias necessárias

## 11. RECOMENDAÇÕES PRIORITÁRIAS
### Críticas (Fazer Imediatamente)
1. [Recomendação com impacto e esforço]
2. ...

### Importantes (Fazer em Breve)
1. [Recomendação com impacto e esforço]
2. ...

### Melhorias (Fazer Quando Possível)
1. [Recomendação com impacto e esforço]
2. ...

## 12. ROADMAP SUGERIDO
- Sprint 1 (Semana 1-2): [Ações]
- Sprint 2 (Semana 3-4): [Ações]
- Sprint 3 (Semana 5-6): [Ações]
- Longo prazo: [Ações]

## 13. CONCLUSÃO
- Avaliação geral do projeto
- Viabilidade de produção
- Próximos passos recomendados

## ANEXOS
- A. Logs de execução completos
- B. Screenshots da dashboard
- C. Lista completa de dependências
- D. Métricas detalhadas
```

## Instruções de Execução

1. **Análise Inicial**: Comece explorando a estrutura do projeto com `listDirectory` recursivo
2. **Leitura de Código**: Leia arquivos principais de cada componente
3. **Execução de Testes**: Execute comandos de teste se disponíveis (npm test, pytest, etc.)
4. **Startup do Projeto**: Tente iniciar backend e frontend
5. **Navegação Web**: Se conseguir acessar a dashboard, teste todas as funcionalidades
6. **Execução de Tools**: Teste cada ferramenta CLI encontrada
7. **Análise de Logs**: Examine logs para identificar problemas
8. **Compilação do Relatório**: Agregue todas as descobertas no formato acima

## Abordagem Recomendada

**Seja:**
- **Autônomo**: Execute tudo que for possível sem intervenção
- **Profissional**: Use terminologia técnica apropriada
- **Detalhado**: Forneça exemplos específicos, não generalizações
- **Prático**: Sugira soluções concretas e implementáveis
- **Objetivo**: Base conclusões em evidências encontradas
- **Crítico**: Identifique problemas reais, não apenas potenciais

**Priorize:**
1. Problemas de segurança críticos
2. Bugs que impedem funcionamento
3. Problemas de performance severos
4. Gaps de funcionalidade importantes
5. Melhorias de código e arquitetura

## Critérios de Avaliação

Use esta escala para pontuações:
- **9-10**: Excelente, pronto para produção
- **7-8**: Bom, pequenos ajustes necessários
- **5-6**: Adequado, melhorias importantes recomendadas
- **3-4**: Problemático, refatoração significativa necessária
- **1-2**: Crítico, requer reescrita

## Entregáveis Esperados

1. **Relatório principal** (markdown formatado)
2. **Lista de issues** priorizadas (crítico/alto/médio/baixo)
3. **Plano de ação** detalhado com estimativas
4. **Screenshots/evidências** das funcionalidades testadas
5. **Logs de execução** relevantes

---

## Exemplo de Prompt para IA

"Você é um auditor técnico sênior especializado em análise de código, arquitetura de software e qualidade. Realize uma auditoria completa e autônoma do projeto Nexus IDE localizado em `projeto-ia-aula/nexus-ide/`. 

Siga o framework de auditoria descrito acima, executando todos os testes, ferramentas e verificações possíveis. Navegue pela dashboard web, teste funcionalidades, execute comandos CLI e analise profundamente o código.

Gere um relatório detalhado no formato especificado, com pontuações objetivas, exemplos concretos de problemas encontrados e recomendações priorizadas e implementáveis.

Seja crítico mas construtivo. Identifique não apenas problemas mas também pontos fortes. Priorize segurança, funcionalidade e manutenibilidade.

Ao final, forneça um plano de ação claro com estimativas de esforço e impacto para cada recomendação."
