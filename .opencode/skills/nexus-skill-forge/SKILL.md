---
name: nexus-skill-forge
description: Criar novas skills opencode durante a conversa para capturar conhecimento do projeto NEXUS e melhorar sessões futuras. Use quando descobrires um padrão, armadilha ou procedimento não-óbvio do repo que valha a pena persistir, ou quando o utilizador pedir para criar/registar uma skill.
version: 1.0.0
status: active
priority: 90
triggers:
  - create a skill
  - skill builder
  - save reusable workflow
  - capture project procedure
tags: [skills, memory, workflow]
---

# Skill Forge — criar skills que melhoram o projeto com o tempo

## Quando criar uma skill

Cria uma skill nova quando **pelo menos uma** condição se verifica:

1. Descobriste uma armadilha não-óbvia que custou tempo (ex.: "pytest corre só de
   `nexus-ide/`, não da raiz").
2. O mesmo procedimento foi preciso 2+ vezes nesta conversa ou no LOG de aprendizagens.
3. O utilizador pediu explicitamente para registar um fluxo de trabalho.

NÃO cries skills para: factos triviais já óbvios no README, decisões únicas de
implementação, ou coisas que pertencam ao AGENTS.md (convenções globais).

## Como criar

Usa `build_skill` quando o utilizador pedir uma skill nova ou uma revisão
versionada. Para aprender com execuções anteriores, consulta primeiro
`discover_skill_candidates`; escolhe só padrões repetidos em traces bem-sucedidos
e passa o nome exato como `experience_candidate` a `build_skill`. Isso cria uma
skill `draft`, nunca ativa automaticamente. Confirma estrutura e metadados com
`list_skills` e `load_skill`; valida os gatilhos e dependências antes de propor
ativação. Um rebuild preserva a versão anterior e incrementa o patch da nova.

1. Pasta + ficheiro: `.opencode/skills/<nome-em-kebab-case>/SKILL.md`; revisões
   podem usar pastas `-v2`, `-v3`, mantendo o mesmo `name` canónico no frontmatter.
2. Frontmatter obrigatório:

```markdown
---
name: <nome-em-kebab-case>
description: <Uma frase com O QUE faz e QUANDO usar; palavras-chave primeiro.>
---
```

3. Corpo: workflow, regras, verificação e exemplo curtos; incluir comandos exatos
   (PowerShell, Windows) só quando verificados. Skills têm orçamento limitado de
   contexto por execução; dividir conhecimento independente em skills pequenas,
   ligadas por dependências quando necessário.
4. Regista a criação numa linha em `.opencode/learnings/LOG.md`:
   `AAAA-MM-DD | skill criada | <nome> | motivo`.

## Manutenção

- Se uma skill existente se mostrar errada/desatualizada, não a alteres sem pedido;
  propõe um rebuild versionado e confirma o novo resultado.
- Repetição no LOG ou num trace gera um candidato para revisão, nunca uma promoção
  automática.
- Skills são ficheiros versionáveis: reporta o caminho e sugere commitá-las para a
  equipa beneficiar.
