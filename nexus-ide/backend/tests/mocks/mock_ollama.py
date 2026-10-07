"""Mock Ollama client for demonstration mode.

Used when Ollama server is not available, simulating AI responses
for testing and demonstration purposes.
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

# Predefined responses for different agents
AGENT_RESPONSES = {
    "ARCHITECT": [
        "Analisando a arquitetura do sistema... Recomendo uma abordagem modular com microsserviços.",
        "O design proposto precisa de ajustes. Sugiro separar as responsabilidades em camadas distintas.",
        "Para escalar corretamente, precisamos considerar cache distribuído e balanceamento de carga.",
    ],
    "RESEARCHER": [
        "Pesquisando as melhores práticas... Encontrei várias abordagens relevantes.",
        "Segundo a documentação, a implementação deve seguir o padrão Repository.",
        "Analisei 5 fontes diferentes e concluo que a abordagem proposta é viável.",
    ],
    "CODER": [
        "Implementando a solução... Aqui está o código otimizado:\n```python\ndef process_data(data):\n    return [x * 2 for x in data if x > 0]\n```",
        "Refatorando para melhor performance... O código agora é 3x mais rápido.",
        "Adicionando tratamento de erros e validação de entrada.",
    ],
    "ANALYZER": [
        "Analisando os dados... Detectei padrões interessantes no comportamento do sistema.",
        "A análise de performance revelou gargalos no processamento de I/O.",
        "Recomendo otimizar as queries do banco de dados para melhor throughput.",
    ],
    "DEBUGGER": [
        "Investigando o bug... Encontrei a causa raiz na função de validação.",
        "O erro ocorre quando o input não está sanitizado. Corrigindo...",
        "Debug completo! O problema estava na condição de corrida entre threads.",
    ],
    "DOCUMENTER": [
        "Documentando a API... Criando especificação OpenAPI completa.",
        "Adicionando exemplos de uso e casos de teste à documentação.",
        "O README agora inclui diagramas de arquitetura e guia de instalação.",
    ],
    "OPTIMIZER": [
        "Otimizando performance... Reduzi o tempo de resposta em 40%.",
        "Aplicando cache inteligente para reduzir carga no banco de dados.",
        "Perfil de memória otimizado. O sistema agora usa 30% menos RAM.",
    ],
    "MICRO": [
        "Processando solicitação rápida... Tarefa delegada concluída.",
        "Validação simples realizada. Input aceito.",
        "Operação de baixa latência executada com sucesso.",
    ],
    "ROUTER": [
        "Analisando solicitação... Roteando para o agente mais apropriado.",
        "Baseado no contexto, recomendo envolver o ARCHITECT para esta tarefa.",
        "Múltiplos agentes podem colaborar. Iniciando coordenação...",
    ],
}

# Conversation flows for multi-agent demos
CONVERSATION_FLOWS = {
    "architecture": [
        ("ARCHITECT", "Vou projetar a arquitetura do sistema. Precisamos de uma base sólida."),
        ("RESEARCHER", "Pesquisando padrões arquiteturais modernos... Encontrei microkernel e event-sourcing."),
        ("ARCHITECT", "Excelente! Vou combinar ambos para criar um sistema escalável."),
        ("CODER", "Posso implementar o núcleo do sistema com esses padrões."),
        ("OPTIMIZER", "Vou garantir que a implementação seja performática desde o início."),
    ],
    "debugging": [
        ("DEBUGGER", "Iniciando investigação do bug reportado..."),
        ("ANALYZER", "Analisei os logs e encontrei anomalias às 14:30."),
        ("DEBUGGER", "Perfeito! Isso confirma minha hipótese sobre race condition."),
        ("CODER", "Posso implementar um fix com mutex adequado."),
        ("DOCUMENTER", "Vou documentar a causa raiz e a solução para referência futura."),
    ],
    "feature": [
        ("ARCHITECT", "Nova feature solicitada. Analisando requisitos..."),
        ("RESEARCHER", "Pesquisando bibliotecas que podem acelerar o desenvolvimento."),
        ("CODER", "Implementando a feature com TDD. Testes primeiro!"),
        ("ANALYZER", "Analisando cobertura de testes... 95% alcançada."),
        ("DOCUMENTER", "Documentando a nova feature com exemplos práticos."),
    ],
}


class MockOllamaClient:
    """Mock client that simulates Ollama responses."""
    
    def __init__(self, demo_mode: bool = True):
        self.demo_mode = demo_mode
        self._conversation_active = False
        self._current_flow: list | None = None
        self._flow_index = 0
    
    async def ping(self) -> bool:
        """Mock ping always returns True in demo mode."""
        return self.demo_mode
    
    async def list_models(self) -> list[str]:
        """Return mock list of models."""
        return ["demo-model:latest", "mock-llama:7b"]
    
    async def check_model_available(self, model_id: str) -> bool:
        """Always True in demo mode."""
        return self.demo_mode
    
    async def chat_stream(
        self,
        model: str,
        messages: list,
        *,
        options: dict | None = None,
    ) -> AsyncIterator[str]:
        """Stream a mock response token by token."""
        # Determine which agent is responding
        agent = self._detect_agent(messages)
        response = self._get_response(agent)
        
        # Stream response character by character with random delays
        for char in response:
            yield char
            await asyncio.sleep(random.uniform(0.001, 0.005))
        
        # Add final newline
        yield "\n"
    
    async def chat_complete(
        self,
        model: str,
        messages: list,
        *,
        options: dict | None = None,
    ) -> str:
        """Non-streaming variant. Returns the full concatenated content string."""
        parts: list[str] = []
        async for token in self.chat_stream(model, messages, options=options):
            parts.append(token)
        return "".join(parts)
    
    def _detect_agent(self, messages: list) -> str:
        """Detect which agent should respond based on message content."""
        if not messages:
            return "MICRO"
        
        last_message = messages[-1] if messages else {}
        content = ""
        if hasattr(last_message, 'content'):
            content = last_message.content.lower()
        elif isinstance(last_message, dict):
            content = last_message.get("content", "").lower()
        
        # Keyword detection for routing
        keywords = {
            "ARCHITECT": ["architecture", "design", "structure", "system", "arquitetura", "design"],
            "RESEARCHER": ["research", "find", "search", "investigate", "pesquisar", "pesquisa"],
            "CODER": ["code", "implement", "write", "function", "código", "implementar"],
            "ANALYZER": ["analyze", "data", "metrics", "performance", "analisar", "análise"],
            "DEBUGGER": ["bug", "error", "fix", "debug", "erro", "corrigir"],
            "DOCUMENTER": ["document", "readme", "docs", "documentação", "documentar"],
            "OPTIMIZER": ["optimize", "speed", "fast", "improve", "otimizar", "performance"],
        }
        
        for agent, words in keywords.items():
            if any(word in content for word in words):
                return agent
        
        return "MICRO"
    
    def _get_response(self, agent: str) -> str:
        """Get a random response for the given agent."""
        responses = AGENT_RESPONSES.get(agent, AGENT_RESPONSES["MICRO"])
        return random.choice(responses)
    
    async def start_conversation_flow(self, flow_type: str) -> AsyncIterator[dict]:
        """Start a multi-agent conversation flow.
        
        Yields messages from different agents in sequence,
        simulating inter-agent communication.
        """
        flow = CONVERSATION_FLOWS.get(flow_type, CONVERSATION_FLOWS["feature"])
        
        for agent, message in flow:
            # Simulate thinking time
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            yield {
                "agent": agent,
                "content": message,
                "timestamp": asyncio.get_event_loop().time(),
            }
    
    async def aclose(self) -> None:
        """Cleanup (no-op for mock)."""
        pass


def create_mock_client() -> MockOllamaClient:
    """Factory function to create a mock client."""
    return MockOllamaClient(demo_mode=True)
