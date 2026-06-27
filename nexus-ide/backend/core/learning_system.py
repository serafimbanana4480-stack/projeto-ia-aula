
"""
Learning System - Aprende com uso real e melhora o sistema.
Analisa logs, identifica padrões, sugere melhorias.
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
import re

class LearningSystem:
    """Sistema que aprende com experiência real."""
    
    def __init__(self):
        self.logs_dir = Path("logs")
        self.learning_file = Path("data/learning.json")
        self.patterns = self._load_patterns()
        
    def _load_patterns(self) -> dict:
        """Carrega padrões aprendidos."""
        if self.learning_file.exists():
            with open(self.learning_file, 'r') as f:
                return json.load(f)
        return {
            "common_errors": {},
            "successful_queries": {},
            "user_preferences": {},
            "performance_bottlenecks": [],
            "recommendations": [],
        }
    
    def analyze_logs(self):
        """Analisa logs recentes e aprende."""
        if not self.logs_dir.exists():
            return
        
        log_files = list(self.logs_dir.glob("*.log"))
        errors = []
        queries = []
        
        for log_file in log_files:
            with open(log_file, 'r') as f:
                for line in f:
                    # Detectar erros
                    if "ERROR" in line or "Exception" in line:
                        error_type = self._extract_error_type(line)
                        errors.append(error_type)
                    
                    # Detectar queries bem-sucedidas
                    if "chat" in line.lower() and "response" in line.lower():
                        queries.append("chat_success")
        
        # Contar erros comuns
        error_counts = Counter(errors)
        self.patterns["common_errors"] = dict(error_counts.most_common(10))
        
        # Guardar
        self._save_patterns()
        
    def _extract_error_type(self, log_line: str) -> str:
        """Extrai tipo de erro da linha de log."""
        # Simplificado - em produção usaria regex mais sofisticada
        if "timeout" in log_line.lower():
            return "timeout"
        elif "connection" in log_line.lower():
            return "connection_error"
        elif "circuit" in log_line.lower():
            return "circuit_breaker_open"
        else:
            return "unknown_error"
    
    def generate_recommendations(self) -> list:
        """Gera recomendações baseadas em aprendizagem."""
        recommendations = []
        
        # Analisar erros comuns
        if "circuit_breaker_open" in self.patterns["common_errors"]:
            count = self.patterns["common_errors"]["circuit_breaker_open"]
            if count > 5:
                recommendations.append({
                    "type": "critical",
                    "issue": "Circuit breaker abrindo frequentemente",
                    "recommendation": "Verificar API keys ou conectividade de providers LLM",
                    "auto_fix": "config/fix_circuit_breaker.py",
                })
        
        if "timeout" in self.patterns["common_errors"]:
            count = self.patterns["common_errors"]["timeout"]
            if count > 10:
                recommendations.append({
                    "type": "performance",
                    "issue": "Timeouts frequentes",
                    "recommendation": "Aumentar timeout ou optimizar queries",
                    "auto_fix": "config/increase_timeouts.py",
                })
        
        self.patterns["recommendations"] = recommendations
        self._save_patterns()
        
        return recommendations
    
    def apply_auto_fixes(self):
        """Aplica correções automáticas baseadas em aprendizagem."""
        recommendations = self.generate_recommendations()
        
        for rec in recommendations:
            if "auto_fix" in rec:
                fix_script = rec["auto_fix"]
                if Path(fix_script).exists():
                    print(f"[AUTO-FIX] Aplicando: {fix_script}")
                    # Em produção, executaria o script
                    # subprocess.run(["python", fix_script])
    
    def _save_patterns(self):
        """Guarda padrões aprendidos."""
        self.learning_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.learning_file, 'w') as f:
            json.dump(self.patterns, f, indent=2)
