# Pesquisa web — ferramentas, pipeline e contrato de saída

Estado verificado em 2026-11-21. Fonte: `backend/tools/web_search.py`,
`backend/tools/web_search_v2.py`, `backend/tools/web_fetcher.py`,
`backend/tools/registry.py` e `frontend/components/chat/MessageBubble.tsx`.

## Ferramentas

| Ferramenta | O que faz | Quando usar |
| --- | --- | --- |
| `web_search` | Lista de fontes. Brave (com chave), DuckDuckGo HTML e Bing HTML sem chave, consultados em paralelo; resultados deduplicados e ordenados. Se nenhum resultado for relevante, cai para Bing News RSS e Stack Overflow. | Lista rápida de candidatos. |
| `search_web_v2` | Igual, com filtro `site:` e janela `recency_days`. | Quando a data importa. |
| `search_and_answer` | Pesquisa, lê as páginas principais em paralelo e devolve `brief` citado + `answer` + `images`. | Pergunta que precisa de resposta com fontes. |
| `deep_research` | O mesmo pipeline do v2, com metadados por fonte (data, imagens, excertos) e orçamento global de ~45 s. | Resposta sintetizada e citável. |
| `fetch_url` | Extrai o texto de uma página, por HTTPS e com proteção SSRF. | Aprofundar uma fonte. |
| `fetch_content_v2` | Extração v2 com imagens, data de publicação e cache SQLite. | Quando precisa de metadados da página. |
| `fetch_and_summarize` | Resumo curto de uma página. | Leitura barata de muitas fontes. |
| `search_images` | Pesquisa de imagens (Brave Images), até 50 resultados seguros. | Só quando o utilizador pede imagens. |

## Pipeline

1. **Pesquisa em paralelo** — `_search_with_fallback` lança os três provedores ao
   mesmo tempo. Cada um tem timeout próprio; `NEXUS_RESEARCH_SEARCH_SECONDS`
   (15 s) limita o conjunto. Um provedor lento ou em baixo não bloqueia os
   restantes. Se todos falharem, a ferramenta devolve erro honesto
   (`SearchProvidersUnavailable`) em vez de "sem resultados".
2. **Deduplicação e relevância** — `_canonical_url` remove `utm_*`/`fbclid`,
   fragmentos e barras finais; `_dedupe_hits` mantém o melhor resultado e junta
   os motores (`brave+bing`). Os resultados do Bing HTML passam por
   `_hit_matches_query`: numa query com dois ou mais termos, um hit tem de
   mencionar pelo menos dois. O endpoint sem chave do Bing degrada para
   correspondências só da primeira palavra (verificado a 2026-11-21), e esses
   hits produzem respostas confiantes sobre o assunto errado. A ausência de
   resultados relevantes é reportada como "sem resultados", não como
   "provedores em baixo": só há `SearchProvidersUnavailable` quando nenhum
   provedor respondeu de todo (verificado ao vivo a 2026-11-21).
3. **Fallbacks estruturados** — quando nenhum hit relevante sobra, entram em
   paralelo o **Bing News RSS** (honra a query completa, devolve o URL direto
   do artigo depois de desembrulhar `apiclick.aspx?url=`) e a **API do Stack
   Overflow** (gratuita, sem chave, 300 pedidos/dia). Se o Bing News não
   devolver itens e a query tiver ano ou nome de mês, repete **uma vez** sem
   esses tokens (`_simplify_news_query`): ao vivo, `Portugal wildfires
   November 2026` dava 0 itens e `Portugal wildfires` dava 4 (2026-11-21). A
   data de publicação vem de cada item, por isso o mês escrito na query não
   acrescenta precisão. O fallback também só é tentado se pelo menos um
   provedor geral respondeu; uma falha total continua a ser um erro honesto.
4. **Leitura concorrente** — `_fetch_many` abre no máximo
   `NEXUS_RESEARCH_MAX_CONCURRENT_FETCHES` (5) páginas, com o tempo restante do
   orçamento global (`NEXUS_RESEARCH_DEADLINE_SECONDS`, 45 s) descontado da
   pesquisa. Cada página tem ainda um teto próprio
   (`NEXUS_RESEARCH_FETCH_SECONDS`, 12 s): um host lento devolve `TimeoutError`
   e não segura as restantes nem transforma o orçamento global em alvo.
   Páginas do Stack Exchange são lidas pela API pública
   (`/questions/{id}?filter=withbody`), porque o HTML responde 403 a clientes
   sem browser — sem isto, toda a fonte do Stack Overflow contava como falha de
   leitura.
5. **Brief** — `_build_research_brief` produz um bloco com fontes numeradas
   `[n] título — URL`, data quando existe, excerto e imagens. O texto total é
   limitado a `NEXUS_RESEARCH_BRIEF_CHARS` (3200).
6. **Imagens úteis** — `_extract_images_bs4` descarta logos, sprites,
   favicons, avatares, placeholders e SVG (marcas vetoriais), bem como
   miniaturas com menos de 300 px (`96x96`, `?width=200`), que de outra forma
   apareceriam como conteúdo ao lado do artigo. As restantes mantêm `alt`,
   `source` e URL absoluto.

## Contrato de saída

`search_and_answer` e `deep_research` devolvem:

- `brief` — primeiro campo do resultado; é o que o modelo deve ler.
- `answer` — resposta curta derivada das páginas.
- `sources` — lista de fontes com `title`, `url`, `snippet`, `published_date`.
- `images` — último campo, lista `{url, alt, source}`; até 12.
- Em falha: `brief=""`, `images=[]` e `error_category` explícito.

A ordem não é acidental. O contexto do ReAct corta resultados grandes ao meio
(`AgentBase._truncate_middle`, 6000 caracteres); colocar `brief` no início e
`images` no fim garante que ambos sobrevivem ao corte.

## Apresentação na UI

`MessageBubble.tsx` renderiza imagens markdown com:

- apenas `http(s)`;
- link para a origem, `loading="lazy"`, `referrerPolicy="no-referrer"`;
- limite de `max-h-[320px]`, largura responsiva e legenda em `alt`;
- qualquer `src` não-HTTP é descartado (sem `<img>` executável).

O modelo é instruído, em `when_to_use`, a incorporar até quatro imagens do
resultado como `![alt](url)` quando o utilizador pede visuais. O agente NEXUS
primário recebe `deep_research` na sua lista (`AgentAction.DEEP_RESEARCH`,
`config/agent_actions.yaml`), inclusive sem projeto selecionado
(`_NO_PROJECT_TOOLS`); `search_and_answer` está registado para a API/MCP, mas
não é anunciado ao agente para não duplicar a escolha.

## Fronteira de confiança

Todo o conteúdo externo atravessa `backend/tools/sanitizer.py` e o registry:

- `is_external_tool` / `EXTERNAL_CONTENT_TOOLS` marcam as ferramentas de rede;
- cada campo de texto é embrulhado em `<external_content nonce=…>` com aviso
  para tratar o bloco como dados, nunca instruções;
- URLs de apresentação rejeitam esquemas não-HTTP, credenciais, localhost,
  `.local`/`.internal` e IPs não globais;
- o transporte HTTP usa `PublicAddressHTTPTransport`, que revalida o destino
  depois de cada redirect.

## Configuração

| Variável | Default | Efeito |
| --- | --- | --- |
| `BRAVE_API_KEY` | vazio | Ativa o provedor Brave. Sem chave, DDG/Bing sustentam a pesquisa. |
| `NEXUS_RESEARCH_SEARCH_SECONDS` | `15` | Prazo da fase de pesquisa. |
| `NEXUS_RESEARCH_DEADLINE_SECONDS` | `45` | Prazo total da chamada de investigação. |
| `NEXUS_RESEARCH_MAX_CONCURRENT_FETCHES` | `5` | Páginas lidas em paralelo. |
| `NEXUS_RESEARCH_FETCH_SECONDS` | `12` | Teto por página; um host lento não segura o lote. |
| `NEXUS_RESEARCH_BRIEF_CHARS` | `3200` | Tamanho máximo do brief. |

## Aprovação e modos

`web_search`, `search_web_v2`, `fetch_url` e `deep_research` estão em
`_CONFIRMATION_TOOLS`: em conversa interativa pedem aprovação. Em modo
autónomo (`assisted`/`mission` com projeto selecionado, ou subagentes do
runtime) são auto-autorizados por estarem em `_AUTONOMOUS_READ_ONLY_TOOLS`.
`search_and_answer`, `search_images`, `fetch_content_v2` e
`fetch_and_summarize` não pedem aprovação em nenhum modo. Esta assimetria é
conhecida; qualquer alteração ao contrato de confirmação deve atualizar
`backend/tests/tools/test_registry_guards.py`.

## Testes

- `backend/tests/tools/test_bing_fallback.py` — descodificação do redirect do
  Bing, parser seguro, fallback e falha honesta.
- `backend/tests/tools/test_web_research_pipeline.py` — concorrência,
  deduplicação, prazos, imagens, brief, migração do cache e allowlist.
- `backend/tests/tools/test_web_search_provider_errors.py` — falha total vs.
  recuperação de um provedor.
- `backend/tests/tools/test_search_quality.py` — termos da query sem acentos e
  sem stopwords, rejeição de hits que só mencionam a primeira palavra, fallback
  para Bing News RSS e Stack Overflow, retry do Bing News sem ano/mês, desembrulho
  de URLs e falha honesta quando os fallbacks também caem (parametrizado sobre
  v1 e v2).
- `backend/tests/tools/test_web_fetcher.py` — cache, Jina, imagem
  decorativa descartada, leitura de perguntas do Stack Exchange pela API e
  recurso ao HTML quando a API falha.
- `frontend/tests/components/chat/MessageBubble.test.tsx` — imagens seguras,
  `src` perigoso descartado e lista de classes.
