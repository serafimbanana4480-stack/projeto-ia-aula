# Relatório de performance da UI do NEXUS

**Data:** 2026-09-27  
**Âmbito medido:** rota `/` do frontend em build de produção, Chat vazio, Chromium local

## Método

O benchmark repetível está em `frontend/scripts/benchmark-chat-ui.mjs` e pode ser executado por `pnpm run benchmark:chat-ui`. Faz cinco navegações/contextos frios por defeito, viewport 1440×1000 e `prefers-reduced-motion: reduce`. Regista FCP, `domInteractive`, bytes JavaScript codificados, número de recursos JS, nós DOM, long tasks durante os primeiros 600 ms após o composer ficar disponível e tempo para abrir o menu de modo.

O harness cria um token local fictício só no contexto Chromium para entrar na rota protegida; `/api/auth/me` recebe uma resposta local e todas as outras chamadas `/api/**` são abortadas. Não envia prompt, não cria run, não chama provider nem exige credenciais. O quarto argumento opcional permite guardar uma captura da primeira amostra.

## Comparação principal — R13 antes / R14 depois

| Métrica | Antes (R13) | Depois (R14) | Variação |
|---|---:|---:|---:|
| Next First Load JS de `/` | 606 kB | 382 kB | -224 kB (-37,0%) |
| JavaScript codificado transferido, mediana de 5 | 628.440 B | 404.444 B | -223.996 B (-35,6%) |
| First Contentful Paint, mediana de 5 | 376 ms | 236 ms | -140 ms (-37,2%) |
| Nós DOM no estado inicial | 466 | 466 | sem alteração |
| Abertura do menu de modo, mediana | 62 ms | 64 ms | +2 ms |
| Long tasks nos 600 ms após o composer | 1 por amostra, 187–190 ms | mediana 0; uma amostra teve 3 até 66 ms | sem bloqueio longo repetido no after |

O highlighter Prism deixou de entrar no bundle inicial e passou para o chunk lazy de `MessageCodeBlock`. O resultado em build da rota `/` manteve 382 kB depois da Ronda 15.

## Smoke visual da R15

Uma execução de uma amostra confirmou o caminho de captura da primeira navegação após a R15: FCP 328 ms, JS 404.454 B, DOM 467, menu 76 ms e zero long tasks. Esta medição **não é comparável** com a série de cinco amostras: foi recolhida uma vez, sob carga variável, e com a captura ativa. Serve apenas para verificar o caminho de screenshot e que o bundle continua a carregar.

As capturas antes/depois foram vistas lado a lado. Ambas mostram o Chat vazio e a composição geral ficou igual. O espaço do toolbar num bloco de código é coberto por teste de componente, não pela captura vazia.

## Limitações

- Chromium local 149.0.7827.55, sem throttling de CPU ou rede; não representa hardware de gama baixa.
- Sem mensagens carregadas, stream contínuo, output extenso, dez agentes, provider real, TTFT, run de ferramenta, memória/heap, React commits ou frame drops.
- A captura usa autenticação local de teste e aborta as restantes APIs; o aviso de sessão/backend ausente é esperado neste cenário e não demonstra um teste live.
- O número de nós mede apenas o DOM deste estado de página.
- O valor de FCP de uma amostra R15 não deve substituir a mediana R14.

## Próximas medições recomendadas

1. Repetir com CPU/rede limitadas e uma conversa representativa carregada.
2. Medir stream sustentado, scroll longo, outputs de tool extensos, frames/long tasks e memória.
3. Executar o fluxo autenticado com backend e provider de teste, sem misturar as medidas locais atuais com resultados live.
