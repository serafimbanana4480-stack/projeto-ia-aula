# QUESTIONS — NX-20261006-A1

Itens realmente bloqueados. Nenhum approval foi inferido de silêncio.

## Q-01 — `HORAS_TOTAIS` não preenchido (bloqueia F5 por inteiro)
**Falta:** duração total da sessão.
**Efeito:** por §6/§11/§12, benchmark T1–T12 e soak ficam `BLOCKED`. Executei apenas inspeção de
baixo risco e 1 probe offline.
**Desbloqueia com:** um valor em horas. Mesmo com tempo, NX-ENV-001 continua a bloquear C:.

## Q-02 — Nenhum SUT autorizado (bloqueia toda a conclusão sobre autonomia)
**Falta:** `SUT_MODELOS_LOCAIS` e/ou `SUT_MODELOS_EXTERNOS_CUSTO_ZERO`.
**Efeito:** `SUT_MODELOS_EXTERNOS_CUSTO_ZERO: []` + `ORCAMENTO_API_USD: 0` ⇒ nenhuma chamada a
provider. Não confirmei preço em catálogo, portanto não chamei (ASSUMPTION-03, I-3).
**Consequência maior:** **esta sessão não diz nada sobre se modelos pequenos conseguem planear,
executar com tools, manter TODOs verdadeiras ou continuar tarefas longas.** Essa era a questão
central do prompt e permanece inteiramente `NOT_MEASURED`.
**Desbloqueia com:** lista de modelos locais instalados, ou autorização + confirmação de preço
zero para um modelo externo.

## Q-03 — Disco C: a 3,99% (bloqueia testes pesados e soak)
**Falta:** um volume de teste autorizado, ou espaço no C:.
**Efeito:** `FOCUSED_ONLY`. Não executei suite completa, build, instalação ou soak.
**Opções:** (a) autorizar um volume separado; (b) decidir o destino dos 733 ficheiros alterados;
(c) aceitar que a auditoria continue focada.

## Q-04 — Autoria das alterações pré-existentes não estabelecida
733 entradas em `git status`, +5 face ao snapshot, sem origem conhecida (NX-ENV-002).
**Efeito:** por I-2, não posso distinguir alterações concorrentes de trabalho a preservar em
muitos ficheiros. Isto torna F3 (correções) arriscado por defeito, independentemente do
conteúdo.
**Desbloqueia com:** indicar quais das alterações são suas e quais devem ser preservadas.

## Q-05 — Nenhum revisor independente disponível
`SUBAGENTES_DISPONIVEIS: false` no template; interpretei restritivamente e executei sozinho
(ASSUMPTION-04). Logo **nenhum finding pode atingir `DONE` (E4)** nesta sessão — todos ficam em
`OPEN`/`CONFIRMED`.
**Desbloqueia com:** autorização para usar subagentes como revisor, ou revisão humana.

## Q-06 — Decisão sobre NX-T-001 (o único patch pronto)
Corrigir 2 linhas num teste de segurança **ativa um oráculo que nunca correu**. Já verifiquei que,
com a correção, os testes passam — mas isso é exactamente o caso em que um auditor não deve
decidir sozinho: se alguém_running implementasse e falhasse, pareceria uma regressão de produto.
Como o ficheiro é untracked e não posso reverter com `git`, o risco de rollback é assimétrico.
**Pergunta:** aplico o patch de `TODO.md` (com preimage + `patches/NX-<ID>.diff`), ou deixa para
decisão humana?

## Q-07 — Escopo da auditoria
Só cobri **F0** e o canto de SSRF de **F1**. As rondas de agentes A–H (§8), a matriz de
capacidades completa, a revalidação dos restantes P1 do relatório anterior (ownership de
sessões/MCP/skills, `HumanOversight`, commits globais, retoma de tarefas, orçamento, TODOs,
tracing) **não foram executadas**.
**Motivo:** `HORAS_TOTAIS` vazio (§6 → "apenas inspeção de baixo risco") e modo restritivo.
**Desbloqueia com:** Q-01 e Q-04. Diga também se prefere as rondas A–H por subagente ou
sequenciais por mim.