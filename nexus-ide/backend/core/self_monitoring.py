
"""
Self-Monitoring System - O projeto monitoriza-se e melhora-se autonomamente.
"""
import psutil
import time
from datetime import datetime

class SelfMonitor:
    """Monitoriza recursos e performance, ajusta configurações autonomamente."""
    
    def __init__(self):
        self.metrics = {
            "cpu_usage": [],
            "memory_usage": [],
            "response_times": [],
            "error_rates": [],
        }
        self.thresholds = {
            "cpu_high": 80,      # %
            "memory_high": 85,   # %
            "response_slow": 2.0,  # segundos
            "error_high": 0.05,    # 5%
        }
    
    def collect_metrics(self):
        """Recohe métricas do sistema."""
        cpu = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory().percent
        
        self.metrics["cpu_usage"].append(cpu)
        self.metrics["memory_usage"].append(memory)
        
        # Manter apenas últimas 100 medições
        for key in self.metrics:
            if len(self.metrics[key]) > 100:
                self.metrics[key] = self.metrics[key][-100:]
        
        return {"cpu": cpu, "memory": memory}
    
    def analyze_and_adjust(self):
        """Analisa métricas e ajusta configurações autonomamente."""
        current = self.collect_metrics()
        
        actions_taken = []
        
        # CPU alto -> Reduzir concorrência
        if current["cpu"] > self.thresholds["cpu_high"]:
            actions_taken.append("Reduzindo concorrência (workers)")
            self._adjust_workers(-1)
        
        # Memória alta -> Limpar caches
        if current["memory"] > self.thresholds["memory_high"]:
            actions_taken.append("Limpando caches")
            self._cleanup_caches()
        
        # Registar ajustes para aprendizagem
        if actions_taken:
            self._log_adjustment(actions_taken)
            
        return actions_taken
    
    def _adjust_workers(self, delta: int):
        """Ajusta número de workers."""
        # Implementação específica
        pass
    
    def _cleanup_caches(self):
        """Limpa caches antigos."""
        # Implementação específica
        pass
    
    def _log_adjustment(self, actions: list):
        """Regista ajustes para aprendizagem futura."""
        log_path = "data/self_monitoring.log"
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as f:
            timestamp = datetime.now().isoformat()
            f.write(f"[{timestamp}] Ajustes: {', '.join(actions)}\n")
