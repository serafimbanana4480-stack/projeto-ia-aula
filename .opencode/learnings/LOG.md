# Log de Aprendizagens do NEXUS

Uma linha por descoberta. Formato: `AAAA-MM-DD | tipo | descritor | lição`.
Tipos: skill-criada, skill-corrigida, armadilha, comando, decisao.
Padrões que aparecem 2+ vezes devem ser promovidos a skill (ver nexus-skill-forge).

---
2026-08-24 | organizacao | reorganizacao-repo | auditorias para docs/auditorias, cobaias/logs/prototipos para nexus-ide/archive; nada apagado
2026-08-24 | armadilha | backend-ativo-porta-8000 | backend NEXUS em execução cria ficheiros-cobaia no workspace; ignorar, não matar
2026-08-24 | armadilha | gitignore-md | nexus-ide/.gitignore ignora *.md com exceções (!docs/**, !NEXUS_*.md); MDs novos fora de docs ficam invisíveis ao git
2026-08-24 | decisao | merge-P1-P12 | codex/phase3-fixes mergeado em main (5fdafcf); conflitos chat*.py eram lógica duplicada — manteve-se upstream nos guardas, lado WIP no envelope durável (_start_primary_run é superset)
2026-08-24 | armadilha | pytest-basetemp-lock | backend ativo segura .pytest_tmp\*\test_nexus.db → usar --basetemp fresco; worktrees de verificação precisam de logs/, data/ e .env copiados
2026-08-24 | armadilha | auto-commit-ciclo | o ciclo autónomo faz "auto: pre-0-proposals cycle" com add -A; pode varrer WIP a meio de operações externas
2026-08-24 | skill-criada | sistema-opencode | skills nexus-backend/nexus-frontend/nexus-skill-forge + agente hermes criados; requerem restart do opencode
2026-08-24 | armadilha | python-stub-windows | "python" literal no subprocess resolve para o stub da Microsoft Store (WindowsApps); usar sempre sys.executable
2026-08-24 | armadilha | pytest-dentro-de-repo | tmp_path dentro do repo nexus-ide faz git descobrir o repo pai; usar GIT_CEILING_DIRECTORIES em testes git
2026-08-24 | decisao | F821-zero | 48 nomes não definidos corrigidos (crashes latentes); política: manter F821/F823 a zero no backend
2026-08-24 | armadilha | suite-bloqueada-colecao | 1 ficheiro de teste com import quebrado interrompe TODA a coleta pytest; verificar coleção antes de investigar falhas
2026-08-24 | decisao | dinheiro-real-audit | B1/B2/B3/B5 corrigidos: cost governor pré-dispatch + usage_ledger persistido + kilo fora do free_only + 401/402 abrem breaker 900s; pendente B4 (preço dinâmico), B6 (Redis multi-worker), B7 (keys em claro)
2026-08-24 | armadilha | early-return-gates | verificação dupla (diário+run) no cost governor era saltada por return antecipado do ramo ilimitado; testar gates compostos sempre
2026-08-24 | decisao | b4-b6-b7-fechados | preço: YAML→catálogo live→conservador (nunca $0 em modo pago); orçamento autoritativo via SQLite partilhado (sem Redis); chaves enc:v1 Fernet derivado de SECRET_KEY com leitura legado transparente
2026-08-24 | armadilha | router-prefix-duplo | main.py inclui routers com prefix="/api"; routers novos não devem repetir /api no próprio prefix
