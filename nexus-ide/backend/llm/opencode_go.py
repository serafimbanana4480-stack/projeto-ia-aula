
"""
OpenCode Go API Integration - Integração REAL e FUNCIONAL.
Substitui o circuit breaker aberto por integração autêntica.
"""
import os
import requests
import json
from typing import Dict, Any, Optional

class OpenCodeGoAPI:
    """Integração com OpenCode Go API (OpenRouter)."""
    
    def __init__(self):
        self.api_key = os.getenv("OPENCODE_GO_API_KEY") or os.getenv("OPENROUTER_API_KEY")
        self.api_base = "https://openrouter.ai/api/v1"
        self.default_model = "anthropic/claude-3.5-sonnet"
        self.timeout = 30
        self.session = requests.Session()
        
    def is_configured(self) -> bool:
        """Verifica se API key está configurada."""
        return bool(self.api_key and self.api_key != "***")
    
    def test_connection(self) -> Dict[str, Any]:
        """Testa conexão com a API."""
        if not self.is_configured():
            return {"success": False, "error": "API key não configurada"}
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            # Testar com uma chamada simples
            response = self.session.get(
                f"{self.api_base}/models",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                return {"success": True, "models": response.json()}
            else:
                return {"success": False, "error": f"Status {response.status_code}: {response.text}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def generate(self, prompt: str, model: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Gera resposta usando LLM via OpenCode Go."""
        if not self.is_configured():
            raise Exception("API key do OpenCode Go não configurada")
        
        model = model or self.default_model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://nexus-ide.local",  # OpenRouter requer
            "X-Title": "NEXUS IDE",  # OpenRouter requer
        }
        
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 2000),
            "stream": False,
        }
        
        try:
            response = self.session.post(
                f"{self.api_base}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            return {
                "success": True,
                "content": result["choices"][0]["message"]["content"],
                "model": result.get("model", model),
                "usage": result.get("usage", {}),
            }
            
        except requests.exceptions.Timeout:
            raise Exception("Timeout: A API demorou muito a responder")
        except requests.exceptions.ConnectionError:
            raise Exception("Erro de conexão: Verifique internet/API")
        except Exception as e:
            raise Exception(f"Erro na chamada LLM: {str(e)}")
    
    def get_available_models(self) -> list:
        """Lista modelos disponíveis."""
        if not self.is_configured():
            return []
        
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            response = self.session.get(
                f"{self.api_base}/models",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("data", [])
            return []
        except:
            return []

# Instância global
opencode_go = OpenCodeGoAPI()
