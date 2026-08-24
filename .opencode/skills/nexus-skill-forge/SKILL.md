---
name: nexus-skill-forge
description: Criar novas skills opencode durante a conversa para capturar conhecimento do projeto NEXUS e melhorar sessões futuras. Use quando descobrires um padrão, armadilha ou procedimento não-óbvio do repo que valha a pena persistir, ou quando o utilizador pedir para criar/registar uma skill.
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

1. Pasta + ficheiro: `.opencode/skills/<nome-em-kebab-case>/SKILL.md` (o nome da pasta
   tem de ser igual ao campo `name`).
2. Frontmatter obrigatório:

```markdown
---
name: <nome-em-kebab-case>
description: <Uma frase com O QUE faz e QUANDO usar; palavras-chave primeiro.>
---
```

3. Corpo: comandos exatos (PowerShell, Windows), regras numeradas não-óbvias, e uma
   secção "Dívida conhecida" se aplicável. Máximo ~60 linhas — skills longas não são
   carregadas.
4. Regista a criação numa linha em `.opencode/learnings/LOG.md`:
   `AAAA-MM-DD | skill criada | <nome> | motivo`.

## Manutenção

- Se durante o trabalho uma skill existente se mostrar errada/desatualizada, corrige-a
  na hora (as skills vivem no repo — são código).
- Promove para skill qualquer padrão que apareça 2+ vezes no LOG.
- Skills são ficheiros versionáveis: sugere commitá-las para a equipa beneficiar.
