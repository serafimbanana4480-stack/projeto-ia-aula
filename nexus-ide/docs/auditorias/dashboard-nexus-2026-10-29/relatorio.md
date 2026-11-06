# Dashboard NEXUS — observações visuais

Capturado em 29 de outubro de 2026 na instância local existente, sem alterar definições ou reiniciar serviços. A observação mostra um ecrã de 1280 × 720 e dados que podiam mudar depois da captura. A avaliação cobre a vista apresentada, não certifica a funcionalidade global nem a acessibilidade da aplicação.

## 1. Entrada e primeira ação — base boa, hierarquia a melhorar

![Topo da dashboard](C:/Users/rodri/Desktop/nexus/nexus-ide/docs/auditorias/dashboard-nexus-2026-10-29/01-topo.png)

A identidade escura e os acentos roxos estão consistentes e discretos. O título, o painel com três indicadores, a navegação horizontal e os quatro atalhos ocupam quase toda a primeira vista; o campo para lançar um objetivo fica abaixo da dobra. Para uma dashboard mais moderna sem exageros, reduziria a altura do cabeçalho e colocaria o objetivo e o estado mais importante mais perto do topo. Manteria os gradientes e as bordas subtis, evitando acrescentar efeitos.

Na captura aparecia «Pouco espaço no disco — 5,4% livre». É uma indicação operacional a confirmar no momento de agir, não uma medição independente da saúde do disco.

## 2. Agora e desempenho — a interpretação das falhas é confusa

![Atividade atual](C:/Users/rodri/Desktop/nexus/nexus-ide/docs/auditorias/dashboard-nexus-2026-10-29/02-agora.png)

O cartão mostra uma sessão com falha e, imediatamente abaixo, «Sem falhas registadas». O código usa contadores diferentes: o estado dos perfis e o número de pedidos falhados. Ambos podem coexistir, mas a frase não diz a que se refere. Uma redação como «0 pedidos falhados» e «1 perfil com falha» ajudaria a perceber a diferença. Antes de corrigir dados ou contadores, é preciso investigar as suas origens e períodos.

## 3. Integrações — estado precisa de contexto

![Integrações](C:/Users/rodri/Desktop/nexus/nexus-ide/docs/auditorias/dashboard-nexus-2026-10-29/03-integracoes.png)

Na captura, OpenRouter e LM Studio aparecem como «Indisponível», mas a última verificação aparece como «—». O painel dos MCP descreve corretamente que apresenta o último teste, não uma ligação em tempo real; mostrava três erros de teste. Isto são estados apresentados pela dashboard, não um diagnóstico independente de indisponibilidade atual. Indicaria melhor quando foi feita a última verificação, a origem do estado e a próxima ação possível. O custo sem dados e os tokens noutra secção precisam também de explicar os respetivos períodos e fontes.

## 4. Agentes — estrutura boa, cartão estreito

![Equipa de agentes](C:/Users/rodri/Desktop/nexus/nexus-ide/docs/auditorias/dashboard-nexus-2026-10-29/05-agentes-completo.png)

Os cartões separam bem os subagentes do advisor. No ecrã observado, porém, os identificadores, estados e contadores das sessões do advisor ficam apertados e parcialmente sobrepostos. O texto auxiliar e alguns rótulos também são muito pequenos. Recomendação: permitir quebra de linha nos dados da sessão e reservar mais largura para o estado; aumentar ligeiramente os rótulos secundários.

## Limites

- Não foram testados todos os botões, o teclado, leitores de ecrã, zoom, contraste medido ou tamanhos de ecrã diferentes.
- A verificação foi visual e de leitura de código pontual. Não se confirmou a causa dos problemas de provider/MCP, nem se afirma que uma ligação esteja atualmente funcional ou falhada.
- A dashboard não foi alterada nesta avaliação.
