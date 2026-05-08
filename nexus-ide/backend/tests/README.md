# Backend Tests — NEXUS IDE

Esta pasta contém a suite de testes do backend usando pytest.

## Estrutura

```
backend/tests/
├── conftest.py              # Fixtures globais (mocks, settings)
├── agents/                  # Testes dos 9 agentes
├── orchestrator/           # Testes de routing, pool, fallback
├── tools/                   # Testes de ReAct tools
├── config/                  # Testes de settings e models.yaml
└── observability/           # Testes de métricas e tracing
```

## Correr Testes

### Todos os testes
```bash
cd backend
pytest tests/ --cov=backend --cov-report=term-missing
```

### Apenas um módulo
```bash
pytest tests/agents/test_base.py
pytest tests/orchestrator/test_router.py
```

### Com verbose
```bash
pytest -v
```

### Apenas testes que falharam na última execução
```bash
pytest --lf
```

## Fixtures

### Fixtures Globais (conftest.py)

- `mock_settings`: Patch de environment variables para Settings
- `models_yaml_dict`: Parse do real `models.yaml`
- `mock_ollama_client`: Mock do cliente Ollama
- `mock_redis`: Mock do cliente Redis

### Como Usar Fixtures

```python
def test_something(mock_settings):
    s = get_settings()
    assert s.ollama_host == "http://test-ollama:11434"
```

## Mocking

### Ollama Client

```python
from unittest.mock import MagicMock

def test_agent_with_mock_ollama(mock_ollama_client):
    mock_ollama_client.chat.return_value = {"message": {"content": "test"}}
    # usar o mock
```

### Redis

```python
def test_with_redis(mock_redis):
    mock_redis.get.return_value.set_result("value")
    # usar o mock
```

### HTTP Requests (httpx)

```python
import respx

@respx.mock
def test_web_search(respx_mock):
    respx_mock.get("https://api.search.brave.com/v1/search").mock_return_value(...)
    # testar
```

## Coverage

O target mínimo é 70%. Para ver coverage detalhado:

```bash
pytest --cov=backend --cov-report=html
# Abre htmlcov/index.html no browser
```

## Debugging Tests

### PDB

```bash
pytest --pdb
# Para no primeiro erro
```

### Print statements

```bash
pytest -s
# Mostra output de print statements
```

### Verificar que testes estão a correr

```bash
pytest --collect-only
# Lista todos os testes sem correr
```

## Adicionar Novos Testes

1. Criar ficheiro na pasta apropriada (ex: `tests/agents/test_new_agent.py`)
2. Importar o módulo a testar
3. Criar função de teste prefixada com `test_`
4. Usar fixtures onde aplicável
5. Correr `pytest` para verificar

Exemplo:

```python
from backend.agents.new_agent import NewAgent

def test_metadata():
    agent = NewAgent()
    assert agent.name == "NEW_AGENT"
    assert agent.model_key == "small"
```

## Convenções

- Nomes de testes descritivos: `test_agent_returns_json_on_valid_input`
- Um assert por teste quando possível
- Usar parametrize para testes similares
- Mockar todos os serviços externos (Ollama, Redis, Brave API, Docker)
