#!/usr/bin/env python3
"""
Teste rápido: Verifica se OpenCode Go API está funcionando.
"""
import os
import requests
from pathlib import Path

print("=" * 60)
print("TESTE RÁPIDO: OPENCODE GO API")
print("=" * 60)

# Ler .env
env_file = Path(".env")
if not env_file.exists():
    print("❌ .env não encontrado!")
    exit(1)

content = env_file.read_text(encoding='utf-8')
api_key = None

for line in content.split('\n'):
    if line.startswith("OPENROUTER_API_KEY="):
        val = line.split('=', 1)[1].strip()
        if val and val != "***":
            api_key = val
            break

if not api_key:
    print("❌ OPENROUTER_API_KEY não encontrada ou inválida!")
    print("   Execute: python scripts/setup_opencode_go.py")
    exit(1)

print(f"✅ API key encontrada (comprimento: {len(api_key)})")

# Testar
print("\n🧪 Testando conexão...")
headers = {"Authorization": f"Bearer {api_key}"}

try:
    resp = requests.get("https://openrouter.ai/api/v1/models", 
                       headers=headers, timeout=10)
    
    if resp.status_code == 200:
        print("✅ CONEXÃO OK!")
        data = resp.json()
        models = data.get("data", [])
        print(f"   {len(models)} modelos disponíveis.")
        
        # Testar chamada simples
        print("\n🧪 Testando chamada LLM...")
        
        payload = {
            "model": "anthropic/claude-3.5-sonnet",
            "messages": [{"role": "user", "content": "Diga 'Funciona!' em português."}],
            "max_tokens": 50
        }
        
        resp2 = requests.post("https://openrouter.ai/api/v1/chat/completions",
                            headers=headers, json=payload, timeout=30)
        
        if resp2.status_code == 200:
            result = resp2.json()
            content = result["choices"][0]["message"]["content"]
            print(f"✅ RESPOSTA: {content}")
            print("\n" + "=" * 60)
            print("SUCESSO! OPENCODE GO API FUNCIONANDO!")
            print("=" * 60)
        else:
            print(f"❌ Erro na chamada: {resp2.status_code}")
            print(f"   {resp2.text[:300]}")
    else:
        print(f"❌ Erro: {resp.status_code}")
        
except Exception as e:
    print(f"❌ Erro: {e}")

print("\nDica: Execute python scripts/setup_opencode_go.py para configurar.\n")
