
"""
LLM Mock - Modo de desenvolvimento.
Permite testar a aplicação sem API keys externas.
"""
import time
from typing import Dict, Any

class MockLLM:
    """Simula respostas de LLM para desenvolvimento."""
    
    @staticmethod
    def generate(prompt: str, **kwargs) -> Dict[str, Any]:
        """Gera resposta simulada."""
        time.sleep(1)  # Simular latência
        
        responses = {
            "olá": "Olá! Sou o assistente NEXUS IDE. Como posso ajudar?",
            "help": "Estou aqui para ajudar com código, debug, e muito mais!",
            "default": f"Entendi: '{prompt[:50]}...'. Como assistente NEXUS, posso ajudar com programação, arquitetura, e muito mais."
        }
        
        # Escolher resposta baseada em palavras-chave
        prompt_lower = prompt.lower()
        for key, response in responses.items():
            if key in prompt_lower:
                content = response
                break
        else:
            content = responses["default"]
        
        return {
            "success": True,
            "content": content,
            "model": "mock/nexus-dev",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }

# Instância global
mock_llm = MockLLM()
