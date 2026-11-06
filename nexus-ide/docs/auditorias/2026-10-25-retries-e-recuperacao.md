# NEXUS IDE — retries da API e recuperação de runs (2026-10-25)

## Âmbito desta alteração

Este registo documenta a correção incremental dos pedidos de chat/provider e da retoma de runs. Não representa certificação completa da auditoria end-to-end do NEXUS IDE.

- O POST /api/chat repete falhas transitórias de rede/HTTP até 10 tentativas totais, com 15 segundos entre tentativas. Mantém o corpo original e a mesma chave Idempotency-Key; falhas não transitórias não entram no ciclo.
- Se o backend já aceitou o pedido e o stream cai, o frontend recupera o mesmo run_id pelo journal SSE e pelo último seq, sem reenviar a mensagem do utilizador.
- Os providers OpenAI compatíveis (LM Studio/OpenRouter) e o cliente Ollama repetem falhas transitórias até 10 tentativas totais, com 15 segundos entre tentativas, preservando o pedido completo. Em streams, a repetição para assim que há conteúdo visível para evitar duplicação.
- O stream do provider deixa de repetir assim que já emitiu texto ou tool call: isso evita duplicar resposta visível ou operações. Erros de autenticação, pedido inválido e quota que exige espera superior ao intervalo seguem para a política de fallback existente.
- Uma repetição idempotente de um run recuperado após restart volta a entrar no ciclo normal de recuperação quando já não existe stream em memória. As rotas de listagem/retoma e a associação idempotente verificam o utilizador dono do run.
- O helper de teste do restart E2E foi corrigido para usar o token recebido; antes registava outro utilizador e escondia o caso cross-tenant.

## Evidência executada

- backend/tests/llm/test_provider_defects.py -k openai_chat: 4 passaram. O servidor HTTP de teste devolveu erros temporários e depois sucesso; os testes verificaram corpo/contexto igual, espera de 15 segundos, limite de 10 pedidos e ausência de retry após saída parcial. O relógio de espera foi substituído no teste; não foram esperados 135 segundos reais.
- backend/tests/llm/test_openai_provider.py backend/tests/llm/test_openrouter_provider.py backend/tests/llm/test_lmstudio_wiring.py: 22 passaram.
- Testes selecionados de OpenRouter, quota e Retry-After: 5 passaram.
- backend/tests/integration/test_run_resume_e2e.py -k test_real_restart_resumes_the_run_the_process_left_open: 1 passou. Usou subprocessos reais do backend, projeto/DB descartáveis e um servidor local com protocolo Ollama scripted. Validou restart, checkpoint e ausência de repetição da escrita confirmada; não é prova de modelo real.
- backend/tests/integration/test_run_resume_e2e.py -k test_idempotency_key_does_not_duplicate_a_running_run: 1 passou. Validou que um retry ativo não cria uma segunda execução.
- Repeti ambos os cenários no fecho desta alteração: 2 passaram em 80,36 s. O modelo Ollama continua scripted nesta prova; a recuperação do processo é real, a inferência não.
- Testes focados de propriedade/rotas/chat: 13 passaram.
- Suites de contexto handoff, fronteira de conteúdo e loop primary: 293 passaram.
- Vitest frontend completo nesta validação: 99 ficheiros, 1.219 testes passaram. `pnpm run type-check` passou. ESLint global terminou sem erros, com 21 avisos de imports/variáveis sem uso e export anónimo.
- Ruff dirigido aos ficheiros backend tocados: All checks passed.
- git diff --check nos ficheiros tocados passou; Git apenas avisou sobre normalização CRLF em dois ficheiros.

## Follow-up: continuidade e isolamento por utilizador

Uma repetição da suite de memória reproduziu uma falha real: um erro registado numa sessão não chegava ao contexto depois de mudar de sessão/modelo. A causa era o carregamento da memória sem o `session_id` atual e o estado resumido antigo que só guardava a tarefa mais recente. A migração agora preserva tarefas antigas e a retoma entre sessões do mesmo utilizador.

Como a memória vive por projeto, também passei o identificador do utilizador autenticado pelos caminhos PRIMARY e legacy. Tarefas, falhas, histórico e resumos em disco ficam separados por utilizador; decisões e objetivo explícito do projeto continuam partilhados.

- `backend/tests/knowledge/test_project_continuity.py`: 9 passaram, incluindo a retoma entre sessões e o teste Alice/Bob que confirma que objetivo, erro e modelo privados não aparecem na conta alheia, enquanto decisões de projeto permanecem partilhadas.
- Suite focada `knowledge`, loop PRIMARY, rotas de modos avançados, recuperação PRIMARY e defeitos de chat: 138 passaram em 185,70 s. A primeira execução apanhou 12 regressões minhas, todas no adaptador legacy por causa de um argumento novo; movi a identidade para o estado autenticado do request e a repetição exata terminou com 138/138.
- `ruff check` dos quatro ficheiros backend tocados, `py_compile` e `mypy --follow-imports=silent backend/knowledge/project_continuity.py`: passaram.
- O mypy dirigido aos dois módulos de rotas ainda reporta 52 erros de tipagem existentes nessas áreas; o ficheiro de continuidade está limpo isoladamente. Isto não limpa nem substitui a dívida global de mypy indicada abaixo.

## Modelos reais e limites da evidência

No estado live verificado agora, backend /health e frontend responderam HTTP 200 (health=ok); as portas locais de Ollama (11434) e LM Studio (1234) não estavam a escutar. Foi feita uma chamada real anterior ao OpenRouter que devolveu stream e permitiu operações reais de leitura/escrita num projeto temporário isolado. Numa verificação live posterior, Gemma respondeu HTTP 429; Nemotron gastou os 32 tokens de saída configurados em raciocínio e não devolveu texto visível. Logo, os retries novos foram validados contra servidor HTTP de teste, não através de uma indisponibilidade real prolongada de um fornecedor.

## Pendente / não certificado

- A suite backend completa foi interrompida por nós após cerca de 2 horas, a 29%, depois de mostrar marcadores de falha. Não foi obtido resumo final nem lista dos testes falhados; o resultado é incompleto.
- Não foram concluídos um soak de várias horas, uma bateria E2E de browser com backend/modelo, nem validação live da sequência de 10 tentativas espaçadas por 15 segundos.
- Gemini e Kimi ainda mantêm políticas próprias, com até 3 tentativas e backoff exponencial; não se afirma que todos os providers externos tenham o mesmo ciclo de 10 × 15 segundos.
- Ruff global falha com 137 problemas; mypy global reporta 2.106 erros em 312 ficheiros. Os ficheiros backend tocados passam Ruff, mas o backend inteiro não está limpo.
- O AGENTS.md pede pnpm 10, mas o package.json fixa pnpm 11.17 e o ambiente tem pnpm 11.25 sem Corepack; não foi alterada a instalação.
- Memória/RAG de longo prazo, coordenação integral de todos os agentes e todas as ferramentas, cancelamento sob carga e recuperação de todos os estados de falha continuam fora da evidência desta correção e exigem validação adicional.

Não declarar o NEXUS IDE pronto para autonomia prolongada com base neste registo.

## Follow-up: exposição da API e diretório do terminal

A revisão encontrou uma combinação insegura de defaults: o backend usava `0.0.0.0`, o Compose publicava a API sem limitar o endereço do host, e `development` permite registo aberto. Um utilizador recém-registado pode chegar às rotas locais de ficheiros e terminal. A rota de terminal também aceitava qualquer diretório existente enviado pelo cliente, sem confirmar que era um projeto conhecido.

Correções aplicadas:

- O default de `BACKEND_HOST` passou para `127.0.0.1`. A publicação padrão de backend, frontend, Redis e Prometheus no Compose também fica em loopback; a API pode ser exposta intencionalmente com `NEXUS_BIND_HOST`.
- O Compose exige `SECRET_KEY` e `JWT_SECRET` em vez de fornecer valores publicados que a própria validação do backend rejeitaria. A configuração do Compose foi analisada como YAML, mas os serviços Docker não foram iniciados nesta validação.
- `validate_configuration()` recusa iniciar com registo aberto e host não-loopback. Para uma instalação de rede, o operador tem de configurar `ALLOW_SELF_REGISTRATION=false` explicitamente.
- `/api/terminal/execute` resolve o diretório pelo mesmo limite de projetos registados que a API de ficheiros. Um diretório não registado recebe HTTP 400 sem chamar o executor.

O `.env` existente não foi alterado. Neste checkout contém `ENVIRONMENT=development` e `BACKEND_HOST=0.0.0.0`, sem `ALLOW_SELF_REGISTRATION` explícito. O processo observado estava ligado a `127.0.0.1`, mas um próximo arranque pelo caminho normal será recusado até o operador limitar `BACKEND_HOST` a loopback ou desligar o registo aberto. Não reiniciei o backend ativo nem alterei a configuração local.

- Testes focados de defaults/settings e terminal: 10 passaram.
- Ruff nos quatro módulos backend alterados: passou.
- O YAML do Compose foi parseado e os endereços locais esperados foram verificados. Não foi validado um arranque Docker.
- O servidor ativo respondeu antes da alteração; esse processo não foi reiniciado, portanto a correção ainda não foi validada por um arranque real do backend.

## Follow-up: refresh de sessão sem interromper a conversa

Foi encontrado mais um caso em que a recuperação podia deixar a interface num estado enganador: quando o POST de chat devolvia 401 e o endpoint de refresh falhava por indisponibilidade transitória, a rejeição do refresh escapava do hook. A sessão podia continuar marcada como streaming, mesmo depois de esgotadas as tentativas.

Correção aplicada em `frontend/hooks/useAgentStream.ts`: falha ao renovar a sessão passa a encerrar o estado de execução, mostrar o erro e manter o histórico da conversa. Não limpa os tokens nem redireciona para login por causa de uma falha temporária. O refresh mantém a chave idempotente em `localStorage`; uma chamada posterior pode recuperar a mesma rotação que o servidor talvez já tenha persistido. Revogação confirmada continua a seguir o caminho de logout existente.

Evidência executada nesta repetição:

- `frontend/tests/lib/auth.test.ts` e `frontend/tests/hooks/useAgentStream.test.tsx`: 46 testes passaram. Cobrem retry do refresh com a mesma chave após 15 segundos, limite de 10 pedidos totais, preservação dos tokens depois de indisponibilidade e manutenção do histórico/estado de chat após falha do refresh.
- `backend/tests/orchestrator/test_auth_route_security.py`, `backend/tests/auth/test_token_revocation.py`, `backend/tests/auth/test_token_types.py`, `backend/tests/config/test_settings.py` e `backend/tests/integration/test_api_endpoints.py`: 43 testes passaram, incluindo recuperação do mesmo par de tokens após simular restart do store de revogação, rejeição de replay com outra chave e limites de terminal/settings.
- `backend/tests/llm/test_provider_defects.py -k openai_chat`: 4 passaram. Um servidor HTTP local controlado confirmou três tentativas com corpo/contexto idênticos, esperas de 15 segundos e o limite de 10 pedidos totais (nove intervalos). O relógio de espera foi simulado; não houve soak de 135 segundos nem chamada a fornecedor real nesta prova.
- Os testes ativos de retry do `OllamaClient` foram reativados/corrigidos após confirmar que a implementação continua a usar HTTP diretamente; antes, uma classe inteira estava marcada como ignorada com a justificação errada de que o cliente era um shim AirLLM. A suite focada passou **70 testes** e verifica as 10 tentativas, nove intervalos de 15 segundos, pedido idêntico e falha final bounded; três testes de constantes/retryable statuses passaram novamente após acrescentar 408/425/429.
- `pnpm run type-check`, Ruff focado nos módulos backend alterados, `py_compile` dos módulos Python afetados e `git diff --check` dos ficheiros desta correção: passaram.

Este teste de integração de protocolo não valida disponibilidade real do OpenRouter, Ollama ou LM Studio. A suite completa de backend, o arranque com a configuração local atual e o soak real de 10 tentativas continuam por validar. O processo backend observado não foi reiniciado; o `.env` local ainda exige rever `BACKEND_HOST=0.0.0.0` em conjunto com registo aberto antes de um arranque normal.

## Follow-up: revogações sobrevivem a restart e contrato do esquema

A revisão da recuperação revelou que tokens revogados e sessões terminadas só estavam na cache do processo. Acrescentei `auth_revocations` ao `schemas.sql`; grava apenas hashes SHA-256 de tokens/sessões e respetiva expiração. O AuthService consulta essa tabela depois de restart e conserva a cache local como atalho. O teste de logout limpa a cache em memória para simular restart e confirma que access e refresh continuam recusados.

O teste existente de paridade exigia igualdade bidirecional Alembic/`schemas.sql`, em conflito com as instruções atuais do repositório, que definem `schemas.sql` como fonte canónica e dizem que Alembic não é usado pela aplicação. Ajustei as asserções para garantir que objetos criados pela cadeia legada continuam presentes no esquema canónico, permitindo novas tabelas e índices apenas no `schemas.sql`. `backend/tests/persistence/test_schema_parity.py`: 9 passaram.

Validação live adicional, sem reiniciar o backend:

- Backend `127.0.0.1:8000/health` e frontend `127.0.0.1:3000`: HTTP 200. Health reporta pressão de disco `warning`, `pressure=true`, `write_blocked=false`; isso impede tratar o estado como totalmente saudável.
- Ollama (11434) e LM Studio (1234): sem listener local.
- Chamada real direta ao OpenRouter, modelo `nvidia/nemotron-3.5-lightning:free`: o pedido terminou em HTTP 200, mas o stream não trouxe texto visível; o provider corretamente devolveu erro de resposta vazia. Não conta como conversa bem-sucedida.
- Chamada real ao OpenRouter, modelo `google/gemma-4-31b-it:free`: o upstream devolveu 429 por limite partilhado; o ciclo interno começou a repetir a cada 15 segundos, e a prova foi cancelada pelo limite de 45 segundos após várias respostas 429. Não confirma 10 tentativas nem uma resposta funcional.
- `mypy --follow-imports=silent backend/auth/service.py` continua a falhar por falta de stubs de `jose` e três retornos `Any` em linhas de tokenização já existentes; não assinalou os novos caminhos de persistência.

As integrações locais e externas não ficam certificadas: a configuração padrão aponta para Ollama, que está indisponível neste momento; o OpenRouter disponível não produziu uma resposta útil nas chamadas live acima. Nenhuma das provas HTTP scripted foi apresentada como resposta de modelo real.







## Retoma da auditoria — identidade das ferramentas e retry live (2026-10-25)

Esta secção acrescenta evidência da retoma atual; não certifica o NEXUS IDE inteiro.

Correções implementadas nesta retoma:

- A identidade autenticada chega agora ao ciclo dos agentes, ferramentas de memória, delegação e ferramentas browser. recall_context e store_memory falham fechadas sem utilizador confiável; o registry substitui qualquer user_id, session_id ou raiz de projeto fornecida pelo modelo por contexto do servidor.
- Sessões browser usam uma chave por utilizador e sessão. A API e o registry propagam essa identidade; pedidos HTTP de navegação, redirecionamentos, subrecursos e WebSockets passam pela verificação de destino público. O requisito mínimo opcional de Playwright foi alinhado com route_web_socket.
- A identidade e os limites Sentinel são propagados para consult_agent, spawn_task e respetivos workers. Testes de contrato foram ajustados aos parâmetros confiáveis que o registry injeta.

Validação desta retoma:

- backend/tests/tools/test_memory_tools.py backend/tests/tools/test_registry_guards.py backend/tests/tools/test_ssrf_tool_guards.py backend/tests/knowledge/test_rag_memory.py backend/tests/knowledge/test_project_continuity.py backend/tests/orchestrator/test_infinity_sentinel_tool_gate.py: **229 passaram, 4 xfailed** em 298,78 s. Os quatro xfail cobrem níveis de risco de ferramentas já conhecidos.
- ruff check nos módulos backend alterados: passou. py_compile dos módulos alterados: passou. git diff --check nos ficheiros desta retoma: passou, com apenas aviso de normalização CRLF em routes/browser.py.
- Testes anteriores do contrato de retry continuam registados acima: frontend de chat, OpenAI-compatible, Ollama e idempotência de run passaram com temporizadores/servidor HTTP controlados. Contam **10 pedidos totais** (pedido inicial + até 9 repetições), intervalos de 15 s, mesma mensagem/contexto e mesma chave idempotente; cancelar interrompe a espera. A retoma SSE liga ao mesmo run_id e after_seq sem fazer POST duplicado.
- Fiz duas chamadas live ao ID gratuito nvidia/nemotron-3.5-lightning:free via OpenRouter. Ambas terminaram sem conteúdo visível; uma foi reportada pelo provider como “OpenAI stream completed without text content”. Não contam como conversação real bem-sucedida nem como prova de retry durante indisponibilidade upstream.
- No estado live consultado: API /health respondeu status=ok com pressão de disco warning (8,28% livre; write_blocked=false). As portas locais Ollama 11434 e LM Studio 1234 estavam fechadas. Playwright não está instalado no ambiente Python, logo não houve browser real.

Riscos que continuam abertos ou sem validação runtime:

- A propriedade de projetos continua sem owner/ACL no esquema. A separação correta depende de definir o contrato de projetos partilhados e migrar dados existentes sem atribuição inventada.
- O teste de conectores MCP customizados ainda pode iniciar comandos stdio escolhidos por um utilizador autenticado; o subprocesso precisa de aprovação/ACL e isolamento apropriado.
- As rotas antigas /workspace/terminal/script e /workspace/terminal/python continuam a exigir revisão: execução de scripts não-Python não usa o sandbox Python e a validação estática Python não limita todas as leituras a uma raiz confiável. Também falta prova de limite de saída e término do subprocesso por timeout na rota de script.
- Browser ainda tem corrida DNS entre a validação e a resolução usada pelo Chromium; não foi estabelecido limite/expiração para sessões browser. Upload ainda lê o ficheiro inteiro antes de rejeitar o excesso de tamanho.
- Não foram executados browser E2E, suite backend completa, soak de várias horas, nem uma chamada de chat completa pela UI com modelo real. Os providers Kimi/Gemini mantêm políticas próprias diferentes do ciclo OpenAI-compatible/Ollama.

O resultado desta retoma melhora isolamento de memória e browser e confirma os ciclos focados de retry, mas deixa o produto em **HOLD / não certificado para autonomia prolongada**.

## Retoma adicional — classificação explícita de risco (2026-10-25)

Os quatro xfail registados na secção anterior eram uma lacuna conhecida e foram corrigidos nesta repetição: approve_pending_commit, git_pull, git_init e git_clone declaram agora risk_level=high. A confirmação continua a ser verificada independentemente pela lista central, e o teste falha se qualquer uma das duas proteções desaparecer.

- backend/tests/tools/test_registry_guards.py e backend/tests/orchestrator/test_infinity_sentinel_tool_gate.py: **101 passaram**, sem xfail, em 130,11 s.
- Ruff, py_compile e git diff --check dirigidos aos módulos/testes tocados passaram.
- A prova live direta ao OpenRouter gratuito não produziu texto visível. O provider devolveu “OpenAI stream completed without text content”; classificar como falha funcional, não como inferência bem-sucedida.

## Verificação final do retry nesta retoma (2026-10-25)

- frontend/tests/hooks/useAgentStream.test.tsx: **21 passaram**. O caso de retry verifica tentativas espaçadas por 15 s com o mesmo contexto, sessão e Idempotency-Key; a recuperação SSE usa o mesmo run e after_seq.
- backend/tests/llm/test_provider_defects.py -k openai_chat: **4 passaram** com servidor de protocolo controlado; inclui stream e completion, contexto/corpo preservados, limite de dez pedidos e não repetir saída parcial.
- backend/tests/tools/test_ollama_client.py: **24 passaram**, incluindo 503/500 transitórios e ciclo fixo de retry do cliente.
- backend/tests/integration/test_run_resume_e2e.py -k idempotency_key_does_not_duplicate_a_running_run: **1 passou** com processos backend reais e fornecedor scripted; a segunda submissão não inicia outro run nem outra chamada de provider.
- Estas provas validam o comportamento do cliente e os limites de repetição. Não simulam 135 segundos reais de espera e não tornam bem-sucedida a chamada OpenRouter live sem conteúdo descrita acima.

## Falha sem resposta do POST (2026-10-25)

A revisão final do fluxo mostrou que uma ligação que ficava pendurada podia esperar pelo watchdog geral do chat (até 30 minutos) em vez de entrar no ciclo de retry. Cada tentativa do POST agora tem timeout de 30 s para a resolução do pedido/resposta. Um timeout aborta apenas essa tentativa, depois espera 15 s e repete o mesmo pedido com a mesma chave idempotente; o sinal de cancelamento do utilizador continua ligado à tentativa/stream ativa. O limite permanece em 10 pedidos totais.

- frontend/tests/hooks/useAgentStream.test.tsx: **22 passaram**. Um teste novo simula o POST que nunca recebe headers, verifica o abort aos 30 s, o intervalo seguinte de 15 s, a chave/contexto preservados e a conclusão do mesmo histórico.
- pnpm run type-check, ESLint dirigido aos dois ficheiros e git diff --check: passaram.
- O timeout de 30 s foi acionado por relógio simulado no teste; não houve espera real de 30 s.

## Execução direta do terminal e compatibilidade da API (2026-10-25)

Uma reprodução local pré-correção mostrou que um utilizador autenticado sem privilégios recebia HTTP 200 nas três rotas `/api/workspace/terminal/{shell,python,script}` e chegava aos executores. A revisão encontrou o mesmo controlo insuficiente em `/api/terminal/execute`, que aceitava `python script.py` para qualquer utilizador autenticado.

As quatro rotas diretas agora exigem a dependência RBAC `require_admin`. O terminal principal continua a resolver o diretório pelo registo de projetos do servidor e pelo utilizador; chamadas a ferramentas de agente continuam a usar a confirmação explícita existente, vinculada a utilizador, sessão, ferramenta e argumentos. Esta alteração não implementa isolamento OS para processos iniciados por um administrador.

As funções frontend legadas enviam `project_path`, mas os três modelos Pydantic só aceitavam `cwd`; isso causava HTTP 422. Os modelos agora aceitam ambos os campos e os handlers usam `project_path` quando fornecido, mantendo `cwd` para compatibilidade.

Validação focada após a correção:

- `backend/tests/orchestrator/test_workspace_execution_auth.py` e `backend/tests/integration/test_api_endpoints.py::TestTerminalEndpoint`: **16 passaram**. Cobrem 401 sem autenticação, 403 antes do executor para não-admins, acesso admin e a resolução do projeto registado.
- `frontend/tests/lib/api.test.ts`: **35 passaram**.
- Ruff focado, `py_compile` dos modelos/rotas/testes e `git diff --check`: passaram.
- Os executores foram substituídos por funções de teste nos testes de autorização; não foi executado script real como prova desta barreira. A reprodução pré-correção também substituiu os executores e só provou a chegada ao handler.

O fluxo `/api/tools/execute` continua disponível através da confirmação explícita de uma ação, vinculada à identidade e aos argumentos; não é tratado como uma rota sem aprovação. Esta distinção preserva a utilização assistida por agentes sem reabrir as rotas diretas. A suite de confirmação do tool registry não foi repetida nesta verificação.

## Follow-up: presets de projeto e gestão global de conectores MCP (2026-10-25)

A revisão dos presets do Editor encontrou que `frontend`, `backend` e `config` eram rejeitados pelo resolvedor, que aceitava apenas a raiz exata registada. `_known_project` passa agora a reconhecer a raiz registada ou um descendente canónico dela, com comparação por segmento de caminho. Um irmão com prefixo semelhante continua recusado; caminhos resolvidos por symlink para fora não correspondem à raiz registada. Isto também mantém a API de ficheiros limitada ao subdiretório selecionado.

A loja MCP é partilhada pela instância e não guarda proprietário por conector. As operações globais de criar, alterar, apagar e testar conectores, assim como o Builder HTTP, agora exigem `require_admin`. A ferramenta `mcp_builder` tem também verificação de identidade confiável e RBAC no registry antes de pedir a confirmação normal. A confirmação explícita continua obrigatória para administradores. Leitura do catálogo mantém autenticação normal.

Validação desta repetição:

- `backend/tests/orchestrator/test_workspace_execution_auth.py`, `test_mcp_connector_auth.py`, `TestTerminalEndpoint` e `TestFilesEndpoint`: **35 passaram**. Incluem as três pastas preset, aceitação/rejeição antes do executor e leitura de ficheiro de um subdiretório registado.
- `backend/tests/orchestrator/test_mcp.py`, `test_mcp_builder_route.py` e `test_mcp_connector_auth.py`: **29 passaram** antes da verificação complementar no registry.
- Após a proteção do Builder chamada pelo agente, `test_mcp_builder_tool_requires_admin_and_keeps_human_confirmation`, a rota HTTP do Builder e a suite de autorização MCP: **15 passaram**; o teste do registry foi repetido após acrescentar o caso sem identidade: **1 passou**.
- `frontend/tests/lib/api.test.ts`: **35 passaram**; o teste de retry de chat do hook: **22 passaram**; type-check e ESLint dirigidos: passaram.
- Ruff focado, `py_compile` dos módulos/rotas/testes e `git diff --check`: passaram. Revisão independente final não encontrou bypass no âmbito dos endpoints MCP e Builder após a proteção no registry.

Estas provas substituem os snapshots anteriores desta mesma retoma para os ficheiros e rotas corrigidos; não são uma certificação do NEXUS inteiro. Os testes usam executores/subprocessos simulados para validar autorização e não afirmam que a execução de comandos está isolada pelo sistema operativo. Um administrador continua a poder configurar e iniciar um processo `stdio` escolhido; esse processo corre com os privilégios do backend.

## Limite de memória na rota de upload (2026-10-25)

A rota de upload lia o ficheiro completo para `bytes` antes de aplicar o limite de 10 MiB. A leitura agora pede no máximo 10 MiB + 1 byte; o validador existente rejeita esse byte extra com a mesma resposta de erro e continua a aceitar ficheiros até 10 MiB. O teste de upload grande verifica o tamanho efetivamente pedido ao `UploadFile.read`, além de confirmar a rejeição.

O parser multipart do Starlette ainda recebe o corpo completo antes de chamar a rota. Ficheiros grandes são guardados em `SpooledTemporaryFile` e podem consumir espaço temporário em disco; limitar o corpo total/parser é uma proteção separada que ainda não foi implementada.

- `backend/tests/tools/test_file_routes.py`: **16 passaram**, incluindo upload válido, limite de tamanho, extensões, magic bytes, traversal, leitura/listagem e escrita dentro de um projeto de teste registado e confiável.
- Ruff focado, `py_compile` dos dois ficheiros tocados e `git diff --check`: passaram; Git emitiu apenas o aviso conhecido de normalização CRLF em `files.py`.

## Limpeza do cancelamento após receber o stream (2026-10-25)

Na repetição final do caminho de retry, confirmei que a tentativa bem-sucedida limpava o timer, mas mantinha o listener de cancelamento ligado ao sinal pai enquanto o stream seguia. Agora chama `dispose()` assim que o POST devolve a resposta, removendo o listener antes de começar a leitura SSE.

- `frontend/tests/hooks/useAgentStream.test.tsx`: **22 passaram**.
- `pnpm run type-check`, ESLint dirigido e `git diff --check`: passaram.

## Auditoria live no backend principal (2026-10-26)

Foram acrescentadas três correções a partir de falhas reproduzidas nesta retoma:

- `OpenAIProvider` agora trata um stream HTTP 200 que termina sem texto nem chamada de ferramenta como falha transitória segura. Repete o pedido completo até 10 tentativas totais, com 15 s entre tentativas, mantendo modelo, mensagens, opções e schemas. Não repete se já tiver emitido saída. Um 404 permanente continua a falhar depressa, sem gastar as nove esperas restantes.
- O Sentinel classificava uma leitura como alteração de ficheiro: o caminho do projeto temporário continha `live`, e a heurística de produção pedia aprovação durante uma leitura. As leituras de caminhos dentro do projeto já não entram na lista de ficheiros afetados; a regressão confirma que uma escrita continua atrás da aprovação.
- O runtime principal agora mapeia explicitamente o veredicto de execução incompleta para `run_failed`/falha persistida. Um agente não pode terminar com uma síntese incompleta e deixar o run marcado como concluído.

### Validação local

- Testes focados do provider, deduplicação/síntese, veredicto da rota principal e Sentinel: **13 passaram, 171 foram excluídos pelo filtro**.
- Ruff, `py_compile` dos módulos/testes tocados e `git diff --check`: passaram.
- A suite completa backend, mypy, type-check/lint/test frontend e browser E2E não foram repetidos nesta retoma.

### Prova real pela API principal

O harness usou uma base SQLite descartável, JWT, lifespan FastAPI e chamadas reais a `/api/chat` pelo OpenRouter. O catálogo live devolveu 467 modelos; foi escolhido `cohere/north-mini-code:free`, declarado gratuito, disponível e com suporte a chat/código/tools no catálogo. Não é prova de faturação fora do catálogo. O sistema local Ollama/LM Studio não estava disponível; Redis recusou ligação e embeddings usaram o fallback determinístico já existente.

- A primeira chamada real fez a ferramenta `write_file`; o ficheiro no projeto isolado ficou com o marcador exato. `read_file` e `read_file_absolute` também leram esse ficheiro após a correção Sentinel.
- O modelo gratuito repetiu chamadas de ferramenta e não produziu uma resposta final válida. O agente devolveu síntese incompleta e o run ficou **failed**, mesmo com o artefacto presente. Isto é um resultado negativo funcional, não um E2E aprovado.
- A chamada real de auto-auditoria leu `backend/llm/openai_provider.py`, mas voltou a repetir ferramentas e terminou sem resposta útil; ficou **failed**. A coordenação multiagente não foi exercitada (zero agentes delegados nesta execução).
- O modelo respondeu à pergunta de memória depois de abrir um lifespan novo. O contexto carregou 4 mensagens, o modelo recuperou a linha CHECK correta e outro processo Python reabriu a DB descartável e confirmou o marcador numa mensagem assistant. O replay da chave idempotente foi aceite sem uma nova chamada ao provider.
- O provider devolveu dois streams sem conteúdo visível nesta execução. Ambos aparecem nos logs como tentativa 1/10 seguida de retry em 15 s. Os testes HTTP locais verificam que o corpo e contexto do pedido permanecem idênticos e que a 10.ª tentativa é o limite. Um fallback grátis NVIDIA também devolveu erro 404 permanente do provider; não foi repetido como se fosse falha transitória.
- O resultado agregado do harness foi **`OVERALL_FULL_APP_REAL_MODEL_E2E_PASS=False`**. O motivo foram as respostas finais vazias/incompletas e a verificação do segundo pedido sem texto, não a escrita ou persistência do marcador. Este run não prova streaming pela UI.

O harness criou backups normais da ferramenta de escrita em `C:\Users\rodri\Desktop\nexus\.nexus\backups\` e manteve-os intactos; os dados de chat e projeto do teste ficaram em `.cache/nexus-live-self-audit-main-app-20261026/run-02bbb56d4f/`.

### Limites ainda abertos

- Modelos grátis reais provaram transporte, tool calls reais, escrita/leitura, retry de resposta vazia e recuperação de memória. Não provaram conclusão fiável de tarefas longas: o modelo observado entrou em repetição e o estado de falha, agora corretamente, permaneceu `failed`.
- Não há nesta prova uma conversa completa no browser, streaming/cancelamento pela UI, soak de horas, RAG sem fallback de embedding, Ollama/LM Studio real, provider pago, fallback de custo variável, ou coordenação efetiva de vários agentes.
- O status final é **HOLD / não certificado para autonomia prolongada**. Prioridades: corrigir o loop de ferramenta/síntese com modelos de produção selecionados, testar os papéis/agentes com os seus contratos de modelo, medir cancelamento/retoma no browser e executar soak com orçamento e observabilidade reais.
