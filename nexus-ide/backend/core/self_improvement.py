
"""
Self-Improvement System - O sistema aprende com erros e sucessos.
"""
import json
from pathlib import Path
from datetime import datetime

class SelfImprovement:
    """Sistema que aprende com experiências e melhora autonomamente."""
    
    def __init__(self, learning_file: str = "data/learning.json"):
        self.learning_file = Path(learning_file)
        self.learning_data = self._load_learning()
        
    def _load_learning(self) -> dict:
        """Carrega dados de aprendizagem."""
        if self.learning_file.exists():
            with open(self.learning_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "successful_patterns": [],
            "failed_patterns": [],
            "optimization_history": [],
            "user_feedback": [],
        }
    
    def record_success(self, pattern: str, context: dict):
        """Regista padrão de sucesso."""
        self.learning_data["successful_patterns"].append({
            "pattern": pattern,
            "context": context,
            "timestamp": datetime.now().isoformat(),
        })
        self._save_learning()
        
    def record_failure(self, pattern: str, error: str, context: dict):
        """Regista padrão de falha."""
        self.learning_data["failed_patterns"].append({
            "pattern": pattern,
            "error": error,
            "context": context,
            "timestamp": datetime.now().isoformat(),
        })
        self._save_learning()
        
    def get_recommendations(self) -> list:
        """Gera recomendações baseadas em aprendizagem."""
        recommendations = []
        
        # Analisar padrões de sucesso
        success_count = {}
        for item in self.learning_data["successful_patterns"]:
            pattern = item["pattern"]
            success_count[pattern] = success_count.get(pattern, 0) + 1
            
        # Top 3 padrões de sucesso
        top_patterns = sorted(success_count.items(), key=lambda x: -x[1])[:3]
        for pattern, count in top_patterns:
            recommendations.append(f"Continuar usando padrão: {pattern} ({count} sucessos)")
            
        return recommendations
    
    def _save_learning(self):
        """Guarda dados de aprendizagem."""
        self.learning_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.learning_file, 'w', encoding='utf-8') as f:
            json.dump(self.learning_data, f, indent=2, ensure_ascii=False)
