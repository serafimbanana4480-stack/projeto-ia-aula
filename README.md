# NEXUS IDE

### Um espaço local para conversar com modelos, configurar bots e acompanhar trabalho num projeto.

O NEXUS IDE junta chat, bots com perfis próprios, grupos, projetos, ferramentas e modelos numa interface web. O frontend usa Next.js e React; o backend usa FastAPI e guarda os dados locais em SQLite.

[Galeria](#galeria) · [Funcionalidades](#funcionalidades) · [Começar](#começar) · [Arquitetura](#arquitetura) · [Verificação](#verificação)

![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white) ![Next.js 15](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white) ![React 19](https://img.shields.io/badge/React-19-149ECA?logo=react&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white) ![Estado](https://img.shields.io/badge/estado-em%20desenvolvimento-8B5CF6)

> **Estado do projeto:** em desenvolvimento. A interface, a configuração de um provider e um teste isolado não provam, por si só, que a inferência, as ferramentas ou uma execução completa estejam operacionais no teu ambiente.

## Galeria

Estas capturas mostram a interface atual com dados de demonstração fornecidos por um fixture local. Não foi contactado nenhum provider de modelos; as imagens servem para mostrar os ecrãs e os estados da aplicação, não resultados de inferência real.

### Dashboard e chat

![Dashboard do NEXUS IDE a 1440×900](docs/screenshots/dashboard-desktop.png)

*O fixture não devolve a verificação de prontidão, e o dashboard apresenta esse estado como não confirmado.*

![Chat principal a 1440×900](docs/screenshots/chat-desktop.png)

*Conversa de exemplo com Markdown e código. Como o fixture não implementa a rota de agentes desta sessão, a interface mostra HTTP 404.*

### Bots

![Editor de capacidades do bot FORGE](docs/screenshots/bot-capabilities-desktop.png)

*O editor mostra as capacidades configuráveis e avisa quando ficheiros ou shell precisam de um projeto selecionado.*

![Conversa do bot FORGE a 1440×900](docs/screenshots/bot-desktop.png)

*Conversa de exemplo e atividade de ferramenta. O provider e o modelo apresentados não foram usados para gerar uma resposta.*

### Grupos

![Grupo em execução a 1440×900](docs/screenshots/group-running-desktop.png)

*Estado de uma execução de exemplo, com participantes e painel de contexto.*

![Grupo concluído a 1920×1080](docs/screenshots/group-done-wide.png)

*Exemplo de passagem entre bots e revisão final. As conclusões são dados do fixture.*

<details>
<summary>Mais ecrãs: incidentes, contexto, projetos, tarefas, definições, editor e telemóvel</summary>

![Incidente de grupo com quatro ocorrências](docs/screenshots/group-incident-desktop.png)

![Separador de ficheiros no contexto do grupo](docs/screenshots/group-context-desktop.png)

![Projetos a 1440×900](docs/screenshots/projects-desktop.png)

![Tarefas a 1440×900](docs/screenshots/tasks-desktop.png)

![Definições a 1440×900](docs/screenshots/settings-desktop.png)

![Editor a 1440×900](docs/screenshots/editor-desktop.png)

*O fixture não fornece a árvore de ficheiros; a captura mostra o erro e o estado vazio apresentados pela interface.*

![Dashboard a 768×1024](docs/screenshots/dashboard-tablet.png)

![Chat a 390×844](docs/screenshots/chat-mobile.png)

![Conversa de bot a 390×844](docs/screenshots/bot-mobile.png)

</details>

## Funcionalidades

| Área | O que podes fazer |
| --- | --- |
| **Chat** | Conversar com o runtime principal, acompanhar mensagens e consultar o contexto da sessão. |
| **Bots** | Manter perfis e conversas individuais; escolher provider, modelo e capacidades do bot. |
| **Grupos** | Conversar por turnos ou iniciar uma execução separada sobre um ficheiro, com as passagens registadas. |
| **Projetos e ficheiros** | Associar conversas a uma pasta e usar as superfícies de projetos, editor e terminal. |
| **Tarefas e dashboard** | Consultar atividade e estados apresentados pela API, incluindo quando algo está indisponível ou por confirmar. |
| **Modelos e integrações** | Consultar providers, modelos e conectores configurados. A presença de um item no catálogo não confirma uma ligação. |
| **Skills e memória** | Consultar instruções reutilizáveis e recursos de contexto expostos pela aplicação. |

As capacidades de ficheiros e shell dos bots dependem de um projeto selecionado. Sem uma pasta autorizada, o backend recusa essas operações; as permissões configuradas no perfil são aplicadas quando cada ferramenta é chamada.

## Começar

### Requisitos

- Python **3.12+**
- Node.js e **pnpm 10.34.9**
- Git
- Um provider local ou credenciais de um provider externo, apenas se quiseres testar inferência real

### Instalação no Windows

No PowerShell:

```powershell
git clone https://github.com/serafimbanana4480-stack/projeto-ia-aula.git
cd projeto-ia-aula/nexus-ide

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .env.example .env

cd frontend
corepack enable
corepack prepare pnpm@10.34.9 --activate
pnpm install --frozen-lockfile
```

Edita `nexus-ide/.env` com a configuração do teu ambiente. Não publiques `.env`, tokens ou chaves.

### Arrancar a aplicação

Abre dois terminais. O backend deve correr a partir de `nexus-ide/`, sem `--reload`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.orchestrator.main:app --host 127.0.0.1 --port 8000
```

No segundo terminal, a partir de `nexus-ide/frontend/`:

```powershell
$env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:8000"
pnpm run dev -- --hostname 127.0.0.1 --port 3000
```

Abre [http://127.0.0.1:3000](http://127.0.0.1:3000). A API fica em [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) e o health check em [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health).

Se uma porta já estiver ocupada, confirma primeiro que processo a está a usar. O script `INICIAR_NEXUS.bat` na raiz contém um caminho específico desta máquina; para um clone novo, usa os comandos acima ou adapta esse caminho.

## Limites que convém conhecer

- A conversa de grupo responde por uma ordem definida e não tem ferramentas. A execução com ficheiro é outro fluxo, também sequencial; as análises anteriores são registadas como não verificadas.
- Um provider ou modelo apresentado na interface não significa que a ligação esteja ativa nem que tenha ocorrido inferência.
- A disponibilidade de browser, MCP, modelos e serviços externos depende da configuração e das dependências instaladas.
- O projeto está em desenvolvimento; confirma o resultado de cada execução antes de o aplicares ao teu código.

## Arquitetura

```mermaid
flowchart LR
  Browser["Browser · Next.js 15 / React 19"] --> API["FastAPI"]
  API --> Runtime["Runtime e orquestração"]
  API --> Bots["Bots e grupos"]
  Runtime --> Providers["Providers de modelos"]
  Runtime --> Tools["Ferramentas com limites de projeto"]
  API --> SQLite[("SQLite")]
  Bots --> SQLite
  Runtime --> SQLite
```

O código principal está em [`nexus-ide/`](nexus-ide/). O esquema de persistência de referência está em [`nexus-ide/backend/persistence/schemas.sql`](nexus-ide/backend/persistence/schemas.sql).

## Verificação

Backend, a partir de `nexus-ide/`:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

Frontend, a partir de `nexus-ide/frontend/`:

```powershell
pnpm run type-check
pnpm run lint
pnpm run test
```

Para regenerar as capturas do README com o fixture local, a partir de `nexus-ide/frontend/`:

```powershell
$env:README_SHOTS_DIR = "../../docs/screenshots"
pnpm exec playwright test e2e/overhaul/readme-shots.spec.ts --config playwright.overhaul.config.ts
```

Este fluxo de capturas usa dados de demonstração e não contacta providers de modelos.

## Mais informação

- [Código da aplicação](nexus-ide/)
- [Auditorias do projeto](nexus-ide/docs/auditorias/)
- [Interface e capturas](docs/screenshots/)
