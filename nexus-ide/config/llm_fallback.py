
# Configuração de Fallback Automático para LLM Providers
# Se um provider falhar, faz fallback para o próximo na lista

FALLBACK_CHAIN = [
    "ollama",      # Local (mais rápido, privacidade)
    "openrouter",  # Cloud (diversos modelos)
    "deepseek",    # Cloud (modelos própios)
    "kimi",        # Cloud (alternativa)
]

# Timeout e retry config
RETRY_CONFIG = {
    "max_retries": 3,
    "timeout": 30,
    "circuit_breaker_threshold": 5,  # Abre após 5 falhas
    "reset_timeout": 60,  # Fecha após 60s
}

# Ollama como fallback local (instalar se não estiver)
OLLAMA_CONFIG = {
    "auto_install": True,
    "default_model": "llama3.2",
    "fallback_if_down": True,
}
