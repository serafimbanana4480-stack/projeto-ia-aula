# Leitura de ficheiros e texto de proteção — 6 de novembro de 2026

## Caso original

Em `real-task-benchmark-20261106-184012/discount/`, o journal
`run-4efab3d83d1f419386c0e5732acc44e0.jsonl` regista a leitura completa no
evento 12, as escritas nos eventos 23 e 26 e a tentativa de testes nos eventos
32–34. O `result.py.txt` conserva o ficheiro final. O aviso e os separadores
estavam dentro do campo `content` da leitura e foram copiados para ambas as
escritas. O Python final tinha erro de sintaxe. O journal mostra a resposta da
ferramenta, mas não constitui uma captura independente do pedido HTTP completo
enviado ao modelo.

O teste de regressão conserva o conteúdo final e verifica que o Python o
rejeita. Outro teste exige que o aviso não esteja no campo de conteúdo. Antes
da alteração, este último falhou; depois passou.

## Alteração e ensaio intermédio

As leituras individuais mantêm o envelope de conteúdo não confiável com nonce,
mas o aviso passa para `content_warning`. Na primeira repetição, em
`real-task-boundary-followup-20261106/`, o modelo deixou de copiar o aviso,
mas copiou os separadores `---` para os dois ficheiros. Ambos ficaram com erro
de sintaxe. Por isso, esses separadores também foram retirados do envelope das
leituras individuais. A marcação de conteúdo não confiável permanece; isto não
prova resistência a injeção para todos os modelos ou cenários.

## Instrumentação

As execuções em `real-task-boundary-captured-20261106/` guardam ainda
`tool_context.jsonl`: resposta completa da ferramenta e texto acrescentado ao
contexto do agente. Isto é uma captura ao nível do runtime, não do pedido HTTP
efetivamente recebido pelo servidor. É ativada somente na bateria opt-in, que
utiliza projetos descartáveis; os dados capturados não devem ser presumidos
seguros para publicação em cenários com dados reais. Os journals guardam as
chamadas e os relatórios e ficheiros finais ficam ao lado. Uma execução
interrompida antes de adicionar a captura está em
`real-task-boundary-final-20261106/` e não é usada como resultado comparativo.

O cenário opcional de recuperação é ativado com
`NEXUS_REAL_TASK_RECOVERY=1`. Pede ao agente que execute primeiro os testes que
falham, corrija o defeito e volte a testar; só constitui prova de recuperação
se o registo mostrar que o erro foi efetivamente encontrado e tratado.
