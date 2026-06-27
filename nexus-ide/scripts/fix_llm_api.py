#!/usr/bin/env python3
"""
Script de Correção Automática - LLM API (OpenCode Go / OpenRouter)
Execute: python scripts/fix_llm_api.py
"""
import os
import sys
import json
import requests
from pathlib import Path

# Cores para terminal
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def print_success(msg):
    print(f"{Colors.GREEN}✅ {msg}{Colors.END}")

def print_error(msg):
    print(f"{Colors.RED}❌ {msg}{Colors.END}")

def print_warning(msg):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.END}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.END}")

def print_header(msg):
    print(f"\n{'='*70}")
    print(msg)
    print('='*70)

def main():
    print_header("CORREÇÃO AUTOMÁTICA - LLM API (OPENCODE GO)")
    
    # 1. Verificar .env
    print_info("Passo 1: Verificando .env...")
    env_path = Path(".env")
    if not env_path.exists():
        print_error(".env não encontrado!")
        print_warning("Crie um .env a partir de .env.example")
        return False
    
    # Ler .env
    with open(env_path, 'r', encoding='utf-8', errors='ignore') as f:
        env_content = f.read()
    
    # 2. Verificar API key
    print_info("Passo 2: Verificando API key do OpenRouter...")
    
    api_key = None
    for line in env_content.split('\n'):
        if line.startswith('OPENROUTER_API_KEY='):
            api_key = line.split('=', 1)[1].strip()
            break
    
    if not api_key or api_key == '***':
        print_error("OPENROUTER_API_KEY não encontrada ou inválida!")
        print_warning("Por favor:")
        print_warning("  1. Aceda: https://openrouter.ai/keys")
        print_warning("  2. Crie uma API key")
        print_warning("  3. Edite o ficheiro .env e adicione:")
        print_warning("     OPENROUTER_API_KEY=sua_api_key_aqui")
        return False
    
    print_success(f"API key encontrada (comprimento: {len(api_key)} caracteres)")
    
    # 3. Testar conectividade
    print_info("Passo 3: Testando conectividade com OpenRouter...")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://nexus-ide.local",
        "X-Title": "NEXUS IDE"
    }
    
    try:
        response = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            print_success("Conexão OK! OpenRouter está acessível.")
            models = response.json()
            print_info(f"Modelos disponíveis: {len(models.get('data', []))}")
        elif response.status_code == 401:
            print_error("API key inválida (401 Unauthorized)")
            print_warning("Verifique se copiou a API key corretamente.")
            return False
        else:
            print_error(f"Erro: Status {response.status_code}")
            print_warning(f"Resposta: {response.text[:200]}")
            return False
            
    except requests.exceptions.Timeout:
        print_error("Timeout: A API demorou muito a responder")
        return False
    except requests.exceptions.ConnectionError:
        print_error("Erro de conexão: Verifique sua internet")
        return False
    except Exception as e:
        print_error(f"Erro inesperado: {e}")
        return False
    
    # 4. Testar chamada LLM real
    print_info("Passo 4: Testando chamada LLM real...")
    
    payload = {
        "model": "anthropic/claude-3.5-sonnet",
        "messages": [{"role": "user", "content": "Diga 'Funciona!' em português."}],
        "temperature": 0.7,
        "max_tokens": 50,
        "stream": False,
    }
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            print_success(f"LLM respondeu: {content}")
            print_success("OPENCODE GO API ESTÁ FUNCIONANDO!")
        else:
            print_error(f"Erro na chamada LLM: Status {response.status_code}")
            print_warning(f"Resposta: {response.text[:300]}")
            return False
            
    except Exception as e:
        print_error(f"Erro na chamada LLM: {e}")
        return False
    
    # 5. Atualizar configuração de providers
    print_info("Passo 5: Atualizando configuração de providers...")
    
    config_path = Path("config/providers.json")
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Garantir que openrouter está enabled e com prioridade 1
        for provider in config.get('providers', []):
            if provider.get('name') == 'openrouter':
                provider['enabled'] = True
                provider['priority'] = 1
                print_success("Provider openrouter configurado com prioridade 1")
                break
        
        # Guardar
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        print_success("Configuração atualizada!")
    else:
        print_warning("config/providers.json não encontrado")
    
    # 6. Reiniciar backend (se estiver a rodar)
    print_info("Passo 6: Reiniciando backend...")
    print_warning("Por favor, reinicie o backend manualmente:")
    print_warning("  1. Ctrl+C no terminal do backend")
    print_warning("  2. Execute: python -m uvicorn backend.orchestrator.main:app --host 0.0.0.0 --port 8000 --reload")
    
    print_header("CORREÇÃO CONCLUÍDA COM SUCESSO!")
    print_success("OpenCode Go API está funcionando e configurada.")
    print_info("Agora:")
    print_info("  1. Reinicie o backend")
    print_info("  2. Teste o chat em http://localhost:3000/chat")
    print_info("  3. Verifique a dashboard em http://localhost:3000/dashboard")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
