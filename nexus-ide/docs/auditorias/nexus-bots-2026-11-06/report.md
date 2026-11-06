# NEXUS Bots — primeira fatia integrada

Data: 2026-11-06. Estado: **PARCIAL**. P0, P1 e P2 do pedido original **não estão concluídos**.

## Auditoria e decisões

- A raiz da aplicação é `nexus-ide/`. O backend usa FastAPI, o runtime PRIMARY, o catálogo de provedores, sessões SQLite e eventos SSE ordenados. O frontend usa Next.js, a sidebar global e `useAgentStream`.
- O checkout já tinha alterações extensas antes deste trabalho. Não foram feitos reset, clean, commit ou substituição integral dos ficheiros alterados. As portas 3000/8000 estavam ocupadas pelo AI Foundry; a prova usou uma cópia isolada e as portas 43811–43813.
- Os endpoints locais de modelos verificados (127.0.0.1:1234, 127.0.0.1:11434 e 172.30.32.1:1234) não responderam. Não houve inferência de modelo real nem chamadas pagas.
- A documentação de estado já assinalava falta de prova de retoma de trabalho após reinício. Uma sessão ou um agendador existente não basta para afirmar autonomia durável.

## Implementado

- Rota `/bots`, entrada na sidebar, interface de mensagens responsiva, pesquisa da lista, arquivo/restauro, painel de informações e formulário de criação/edição com predefinições editáveis.
- Perfil, provedor e modelo por bot, com consulta explícita ao catálogo existente. O endpoint e as credenciais continuam a ser definidos nas configurações globais do NEXUS. A descoberta de modelos não é apresentada como prova de inferência.
- `bot_profiles` é um acrescento ao esquema canónico `backend/persistence/schemas.sql`. Cada perfil fica ligado a uma sessão normal do NEXUS; mensagens, eventos e execução continuam a usar a infraestrutura existente. `init_db` aplica o esquema também a bases existentes. Remover um bot oculta-o e conserva a sessão e o histórico.
- O backend resolve o perfil a partir da sessão autenticada, fixa o provedor/modelo, ignora o projeto e os parâmetros de execução enviados pelo cliente e força uma conversa sem ferramentas. Não usa a via legacy como fallback. Memória global do agente e quadro partilhado não são carregados nem escritos neste caminho.
- Streaming, histórico paginado, Markdown/código e pedido de cancelamento reutilizam os componentes e contratos existentes. O consumidor do modelo é interrompido quando a entrada de cancelamento é sinalizada. O estado apresentado continua a distinguir pedido de paragem de confirmação do backend.
- O botão flutuante Infinity deixou de se sobrepor ao compositor na rota `/bots`.

Ficheiros criados ou alterados nesta fatia:

- Backend: `backend/persistence/schemas.sql`, `backend/persistence/bots.py`, `backend/orchestrator/main.py`, `backend/orchestrator/routes/bots.py`, `backend/orchestrator/routes/chat.py`, `backend/orchestrator/routes/chat_primary.py`, `backend/orchestrator/routes/sessions.py` e `backend/agents/base.py`.
- Frontend: `frontend/app/bots/page.tsx`, `frontend/components/bots/BotsWorkspace.tsx`, `frontend/components/InfrastructureProviders.tsx`, `frontend/components/layout/Sidebar.tsx`, `frontend/components/layout/shellRouteConfig.ts` e `frontend/lib/bots.ts`.
- Verificação: `backend/tests/orchestrator/test_bots.py`, `frontend/tests/components/bots/BotsWorkspace.test.tsx`, `frontend/tests/components/layout/Sidebar.test.tsx`, `frontend/scripts/verify-bots-isolated.mjs` e `frontend/scripts/bots-stub-scenario.json`. Este relatório e as cinco capturas ficam em `docs/auditorias/nexus-bots-2026-11-06/`.

## Evidência

- **TESTED:** 64 testes backend passaram numa base temporária: bots, cancelamento, chat, recuperação do runtime, isolamento entre utilizadores e compatibilidade de migração. O teste dos bots inclui uma tentativa de `write_file` produzida pelo provedor de teste: foi recusada, sem invocação de ferramenta.
- **TESTED:** suite frontend existente: 107 ficheiros, 1.269 testes passaram. Após a paginação, os testes focados da área Bots e sidebar passaram (3 testes). Surgiram avisos React `act(...)` em testes existentes.
- **TESTED:** ESLint dos ficheiros frontend alterados e Ruff dos novos módulos/testes backend passaram. TypeScript e build Next passaram numa cópia isolada com tipos de rotas gerados. O `tsc` inicial no checkout original encontrou tipos gerados antigos sem `/bots`; esses artefactos preexistentes não foram substituídos.
- **MEASURED:** o relatório Next indicou 393 kB de First Load JS para `/bots` antes de tornar o realce de código lazy e 170 kB depois, no mesmo ambiente isolado. São valores de build, não uma medição de velocidade real.
- **TESTED:** Chromium em 1440×900 e 390×844 contra backend/SQLite isolados e servidor HTTP OpenAI-compatible **simulado**: login, criação, catálogo, streaming, recarga, arquivo/restauro e apresentação mobile. A 390 px não se observou overflow horizontal; isto não é uma prova em iOS/Android físicos.
- **TESTED:** uma geração simulada foi cancelada depois de o backend indicar `running`; o estado `cancelled` manteve-se depois do tempo de conclusão normal do servidor de teste. A última prova registou 103 ms até observar o estado cancelado. Um servidor real pode não interromper o seu próprio cálculo ao perder a ligação.
- **TESTED:** um reinício real do backend isolado recuperou o perfil Pixel e as duas mensagens persistidas. Não foi testada a retoma de uma edição ou missão em curso.
- **NOT_MEASURED:** inferência real, tempo de resposta com GPU, custo real, acessibilidade automatizada, dispositivos físicos, testes de longa duração e recuperação de efeitos sobre ficheiros.

As imagens nesta pasta mostram dados de teste e uma resposta explicitamente simulada. A regra existente `*.png` ignora-as no Git, embora continuem disponíveis localmente. O script `frontend/scripts/verify-bots-isolated.mjs` exige uma base descartável e um servidor de teste local identificado; `frontend/scripts/bots-stub-scenario.json` fornece o cenário. Não aponta o teste para a base de produção.

## Limites

Ainda não existem grupos de bots, delegação entre perfis, permissões de ferramentas por bot, operações em projetos, missões duráveis, agendamento de missões, recuperação de efeitos, voz, anexos, edição/regeneração de mensagens, pesquisa no conteúdo do histórico ou controlo de custos por bot. O modo atual é apenas conversa sem ferramentas. A geração em curso não está garantida ao sair da rota, porque o hook existente cancela no unmount. As configurações de temperatura, raciocínio, voz e endpoints individuais também não estão implementadas. Não há prova de ausência de regressões em toda a aplicação ou de robustez em produção.

## Arranque manual

Confirmar primeiro que as portas 8001/3001 estão livres e que as credenciais locais do NEXUS estão configuradas. Os comandos seguintes desativam os serviços de fundo para uma primeira utilização controlada; não ativam agendamentos autónomos.

Na última medição, a unidade C: tinha cerca de 29,81 GiB livres (3,13%). O limite padrão do disk guard é 5%, pelo que pode bloquear novas gerações ou artefactos. Na prova isolada o limite foi reduzido apenas para o teste; não foi alterada a configuração normal do utilizador nem apagado espaço automaticamente. A cópia isolada dos testes ficou em `%TEMP%\nexus-bots-preview-aea2664337dd46f0bed356255b20a6af` e ocupava cerca de 2,03 GiB, excluindo a junction para `node_modules`; os processos de teste foram encerrados e a pasta foi preservada.

Terminal 1:

```powershell
cd C:\Users\rodri\Desktop\nexus\nexus-ide
$env:NEXUS_BACKGROUND_SERVICES = 'off'
$env:NEXUS_ALLOW_DEGRADED_STARTUP = '1'
$env:ALLOWED_ORIGINS = 'http://127.0.0.1:3001,http://localhost:3001'
.venv\Scripts\python.exe -m uvicorn backend.orchestrator.main:app --host 127.0.0.1 --port 8001
```

Terminal 2, com pnpm 10 conforme o repositório:

```powershell
cd C:\Users\rodri\Desktop\nexus\nexus-ide\frontend
$env:NEXT_PUBLIC_API_URL = 'http://127.0.0.1:8001'
pnpm run dev --hostname 127.0.0.1 --port 3001
```

Abrir `http://127.0.0.1:3001/bots`, autenticar e configurar um provedor/modelo realmente disponíveis. A aplicação faz uma atualização aditiva do esquema SQLite no arranque; a prova não usou a base habitual do utilizador. O pnpm encontrado nesta máquina era 11.25.0, pelo que as verificações acima foram executadas com os binários locais instalados, sem instalar pacotes.
