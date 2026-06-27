
"""
LLM Fallback Chain - MODO DESENVOLVIMENTO.
Usa MockLLM se não houver API keys.
"""
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Verificar se estamos em modo de desenvolvimento
DEV_MODE = os.getenv("ENVIRONMENT", "development") == "development"

if DEV_MODE:
    from backend.llm.mock_llm import mock_llm
    logger.info("🔧 MODO DESENVOLVIMENTO: Usando MockLLM")
else:
    from backend.llm.opencode_go import opencode_go


class LLMFallbackChain:
    """Gere LLM com fallback e modo desenvolvimento."""
    
    def __init__(self):
        self.dev_mode = DEV_MODE
        
    def call(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Chama LLM (real ou mock)."""
        if self.dev_mode:
            logger.info("🔧 Usando MockLLM (modo desenvolvimento)")
            return mock_llm.generate(prompt, **kwargs)
        else:
            # Tentar OpenCode Go real
            try:
                return opencode_go.generate(prompt, **kwargs)
            except Exception as e:
                logger.error(f"Erro no LLM real: {e}")
                raise

# Instância global
llm_chain = LLMFallbackChain()
