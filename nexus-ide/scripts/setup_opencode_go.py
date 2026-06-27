#!/usr/bin/env python3
"""
Configurador da API Key do OpenCode Go (OpenRouter)
Execute: python scripts/setup_opencode_go.py
"""
import os
from pathlib import Path

print("=" * 70)
print("CONFIGURADOR DA API KEY - OPENCODE GO (OPENROUTER)")
print("=" * 70)

env_file = Path(".env")

# 1. Verificar se .env existe
if not env_file.exists():
    print("\n❌ .env não encontrado! Crie um a partir de .env.example")
    exit(1)

# 2. Ler .env atual
content = env_file.read_text(encoding='utf-8')

# 3. Pedir API key
print("\n📝 Para obter uma API key:")
print("   1. Aceda: https://openrouter.ai/keys")
print("   2. Faça login (Google/GitHub)")
print("   3. Clique 'Create Key'")
print("   4. Copie a key (sk-or-v1-...)\n")

api_key = input("Coloque sua API key aqui: ").strip()

if not api_key:
    print("\n❌ API key vazia! Abortando.")
    exit(1)

if not api_key.startswith("sk-or-"):
    print("\n⚠️  AVISO: API key não começa com 'sk-or-'")
    print("   (Mas pode estar correta se for outro provider)")
    confirm = input("Continuar mesmo assim? (s/N): ").strip().lower()
    if confirm != 's':
        exit(1)

# 4. Atualizar .env
print("\n🔧 Atualizando .env...")

lines = content.split('\n')
new_lines = []
found_opencode = False
found_openrouter = False

for line in lines:
    if line.startswith("OPENROUTER_API_KEY="):
        new_lines.append(f"OPENROUTER_API_KEY={api_key}")
        found_openrouter = True
    elif line.startswith("OPENCODE_GO_API_KEY="):
        new_lines.append(f"OPENCODE_GO_API_KEY={api_key}")
        found_opencode = True
    else:
        new_lines.append(line)

# Adicionar se não encontrou
if not found_openrouter:
    new_lines.append(f"OPENROUTER_API_KEY={api_key}")
if not found_opencode:
    new_lines.append(f"OPENCODE_GO_API_KEY={api_key}")

# Escrever
env_file.write_text('\n'.join(new_lines), encoding='utf-8')

print("   ✅ .env atualizado!")

# 5. Testar conexão
print("\n🧪 Testando conexão com OpenRouter...")
try:
    import requests
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get("https://openrouter.ai/api/v1/models", 
                   headers=headers, timeout=10)
    
    if resp.status_code == 200:
        print("   ✅ CONEXÃO OK! API key válida.")
        data = resp.json()
        models = data.get("data", [])
        print(f"   ✅ {len(models)} modelos disponíveis.")
        
        # Listar alguns
        print("\n   Primeiros 5 modelos:")
        for i, model in enumerate(models[:5], 1):
            print(f"      {i}. {model.get('id', 'N/A')}")
            
    elif resp.status_code == 401:
        print("   ❌ ERRO 401: API key inválida!")
        print("      Verifique se copiou corretamente.")
    else:
        print(f"   ❌ ERRO {resp.status_code}: {resp.text[:200]}")
        
except Exception as e:
    print(f"   ❌ ERRO de conexão: {e}")

print("\n" + "=" * 70)
print("CONFIGURAÇÃO CONCLUÍDA!")
print("=" * 70)
print("\nAgora execute: make dev (ou terminal separados)")
print("Ou teste com: python scripts/test_llm_opencode.py\n")
