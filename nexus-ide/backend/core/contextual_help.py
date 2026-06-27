
"""
Contextual Help System - Ajuda o utilizador baseada no contexto atual.
"""
from typing import Dict, List

class ContextualHelp:
    """Fornece ajuda relevante baseada no que o utilizador está a fazer."""
    
    def __init__(self):
        self.help_topics = self._load_help_topics()
        
    def _load_help_topics(self) -> Dict[str, Dict]:
        """Carrega tópicos de ajuda."""
        return {
            "chat": {
                "title": "Usar o Chat",
                "content": "Digite sua mensagem e pressione Enter. Use @ para mencionar agentes.",
                "shortcuts": ["Ctrl+K: Procurar", "Ctrl+Enter: Enviar"],
            },
            "dashboard": {
                "title": "Dashboard",
                "content": "Visualiza o estado do sistema, providers LLM e estatísticas de uso.",
                "shortcuts": ["F5: Refresh", "Ctrl+D: Alternar painel"],
            },
            "mission_control": {
                "title": "Mission Control",
                "content": "Gere missões multi-agente e acompanha progresso.",
                "shortcuts": ["Space: Pausar/Retomar", "Ctrl+A: Selecionar todos"],
            },
        }
        
    def get_help(self, context: str) -> Dict:
        """Retorna ajuda para o contexto atual."""
        if context in self.help_topics:
            return self.help_topics[context]
        return {
            "title": "Ajuda",
            "content": "Bem-vindo ao NEXUS IDE. Selecione uma opção no menu para começar.",
            "shortcuts": [],
        }
    
    def search_help(self, query: str) -> List[Dict]:
        """Procura ajuda baseada em palavras-chave."""
        results = []
        query_lower = query.lower()
        
        for topic_key, topic_data in self.help_topics.items():
            if (query_lower in topic_data["title"].lower() or
                query_lower in topic_data["content"].lower()):
                results.append({"topic": topic_key, **topic_data})
                
        return results
