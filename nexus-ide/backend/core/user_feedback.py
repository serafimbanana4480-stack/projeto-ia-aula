
"""
User Feedback System - Melhora interação baseada em feedback.
"""
from typing import Dict, Any
import json
from datetime import datetime

class UserFeedbackSystem:
    """Recohe e processa feedback do utilizador."""
    
    def __init__(self):
        self.feedback_data = []
        self.improvement_suggestions = []
        
    def collect_feedback(self, user_id: str, feedback: Dict[str, Any]):
        """Recohe feedback do utilizador."""
        entry = {
            "user_id": user_id,
            "feedback": feedback,
            "timestamp": datetime.now().isoformat(),
            "processed": False,
        }
        self.feedback_data.append(entry)
        self._save_feedback()
        
        # Processar imediatamente se for crítico
        if feedback.get("severity") == "critical":
            self._process_critical_feedback(entry)
            
    def _process_critical_feedback(self, feedback: Dict):
        """Processa feedback crítico imediatamente."""
        print(f"[FEEDBACK] Crítico recebido: {feedback}")
        # Implementação: notificar desenvolvedores, criar issue, etc.
        
    def analyze_feedback(self) -> Dict[str, Any]:
        """Analisa feedback e gera insights."""
        analysis = {
            "total_feedback": len(self.feedback_data),
            "by_type": {},
            "common_issues": [],
            "improvement_areas": [],
        }
        
        # Contar por tipo
        for entry in self.feedback_data:
            feedback_type = entry["feedback"].get("type", "unknown")
            analysis["by_type"][feedback_type] = analysis["by_type"].get(feedback_type, 0) + 1
            
        return analysis
    
    def _save_feedback(self):
        """Guarda feedback para análise futura."""
        feedback_path = "data/user_feedback.json"
        Path(feedback_path).parent.mkdir(parents=True, exist_ok=True)
        with open(feedback_path, 'w', encoding='utf-8') as f:
            json.dump(self.feedback_data, f, indent=2, ensure_ascii=False)
