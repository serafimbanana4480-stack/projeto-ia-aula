# Bateria inicial de tarefas reais

Esta bateria mede tarefas de alteração de código através do runtime PRIMARY com
um modelo local real. Não usa o browser nem a rota HTTP. Cada cenário cria um
projeto descartável, apresenta um teste de regressão e conserva um ficheiro com
trabalho anterior. Um processo independente verifica o comportamento antes e
depois, com casos adicionais que não são colocados no projeto do agente. Os
hashes identificam ficheiros alterados, criados ou removidos fora do alvo.
Ficheiros novos em `.nexus/` são assinalados à parte, sem atribuir autoria;
alterações a ficheiros `.nexus/` que já existiam continuam a ser inesperadas.

## Executar

A partir de `nexus-ide/`, com um servidor LM Studio compatível ativo em loopback:

```powershell
$env:NEXUS_REAL_TASK_URL = 'http://127.0.0.1:1234/v1'
$env:NEXUS_REAL_TASK_MODEL = '<id exato do modelo carregado>'
$env:NEXUS_REAL_TASK_ARTIFACTS = '<pasta vazia existente para esta execução>'
.venv\Scripts\python.exe -m pytest backend/tests/integration/test_real_task_benchmark.py -q -s
```

Usar uma pasta nova por execução; a bateria recusa reutilizar as pastas dos
cenários. `NEXUS_REAL_TASK_TIMEOUT` define o limite por cenário em segundos
(180 por defeito). Sem URL ou modelo, os testes ficam ignorados. O endpoint
é restrito a localhost, mas o código do agente e o projeto não correm numa
sandbox de segurança: só usar modelos e servidores locais de confiança.
O destino dos backups é redirecionado para os artefactos da experiência, para
evitar que projetos temporários dentro de um checkout escrevam no seu backup.

Cada pasta contém o relatório, eventos e ficheiro final quando disponível. O
oráculo tem de falhar antes da execução; o teste só passa se depois passar, o
alvo mudar e não houver outras alterações. A resposta e as chamadas ficam
registadas para revisão, não são avaliadas automaticamente como verdadeiras.
O custo fica como não medido; o nome de modelo registado é o pedido, não uma
prova independente do modelo efetivamente servido.

Os dois casos atuais cobrem bugs pequenos e proteção de ficheiros existentes.
Não cobrem projeto grande, alteração de funcionalidade, contexto longo,
interrupção, skills/MCP, isolamento de memória, watchdog ou honestidade da
resposta. Também não demonstram que o agente executou testes mesmo quando o
oráculo passa. Comparar configurações exige repetir os mesmos cenários e
guardar relatórios separados; duas tarefas e uma execução não permitem
conclusões estatísticas sobre melhorias.

## Ensaio de 6 de novembro de 2026

Na execução `real-task-benchmark-20261106-184012`, com o modelo pedido
`lfm3-1.7b-uncensored`, os dois cenários falharam. Na paginação, após 99,49 s
não houve alteração do alvo e o oráculo continuou a falhar. No desconto, houve
duas escritas e uma tentativa de testes, mas o ficheiro final incluiu texto de
delimitação de conteúdo externo e tinha erro de sintaxe; a execução atingiu o
limite de 180 s. A resposta registada ficou vazia nos dois casos. O runtime
foi executado diretamente, com integração de missão desativada e política de
ferramentas restringida pelo ensaio; não representa o percurso HTTP completo.

Os relatórios desse primeiro ensaio são anteriores à separação de `.nexus/`
e incluem os novos ficheiros de continuidade entre alterações inesperadas.
Nesse ensaio o mecanismo normal também criou dois backups em
`nexus/.nexus/backups/`; o destino foi depois isolado para execuções futuras,
mas essa alteração ainda não foi comprovada com outra execução do modelo.
