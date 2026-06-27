
"""
Auto-Configuration System - Configura-se autonomamente baseado no ambiente.
"""
import os
import platform
from pathlib import Path

class AutoConfig:
    """Detecta ambiente e configura-se autonomamente."""
    
    def __init__(self):
        self.system = platform.system()
        self.python_version = platform.python_version()
        self.has_gpu = self._detect_gpu()
        self.has_docker = self._detect_docker()
        
    def generate_config(self) -> dict:
        """Gera configuração otimizada para o ambiente."""
        config = {}
        
        # Configurações baseadas no Sistema Operativo
        if self.system == "Windows":
            config["path_separator"] = "\\"
            config["line_ending"] = "\r\n"
            config["recommended_editors"] = ["vscode", "notepad++"]
        else:
            config["path_separator"] = "/"
            config["line_ending"] = "\n"
            config["recommended_editors"] = ["vim", "nano", "vscode"]
        
        # Configurações baseadas em hardware
        if self.has_gpu:
            config["use_gpu"] = True
            config["llm_acceleration"] = "cuda"  # ou "metal" para Mac
        else:
            config["use_gpu"] = False
            config["llm_acceleration"] = "cpu"
            
        # Configurações baseadas em disponibilidade
        if self.has_docker:
            config["use_docker"] = True
            config["recommended_deployment"] = "docker-compose"
        else:
            config["use_docker"] = False
            config["recommended_deployment"] = "local"
            
        return config
    
    def _detect_gpu(self) -> bool:
        """Detecta se tem GPU disponível."""
        try:
            import torch
            return torch.cuda.is_available()
        except:
            return False
    
    def _detect_docker(self) -> bool:
        """Detecta se Docker está disponível."""
        try:
            import subprocess
            result = subprocess.run(["docker", "--version"], capture_output=True)
            return result.returncode == 0
        except:
            return False
    
    def apply_config(self):
        """Aplica configuração gerada."""
        config = self.generate_config()
        
        # Guardar em .env.auto
        env_auto_path = ".env.auto"
        with open(env_auto_path, 'w', encoding='utf-8') as f:
            f.write("# Auto-generated configuration\n")
            for key, value in config.items():
                f.write(f"{key.upper()}={value}\n")
        
        print(f"[AUTO-CONFIG] Configuração auto-gerada: {env_auto_path}")
        return config
