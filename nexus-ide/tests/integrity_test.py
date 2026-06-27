
"""
Teste de Integridade - Verifica se tudo está a funcionar.
Executar antes de cada deploy.
"""
import requests
import time
import sys

def test_backend_health():
    """Testa se backend está saudável."""
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        print("✅ Backend health: OK")
        return True
    except Exception as e:
        print(f"❌ Backend health: FALHOU - {e}")
        return False

def test_frontend_loads():
    """Testa se frontend carrega."""
    try:
        response = requests.get("http://localhost:3000", timeout=5)
        assert response.status_code == 200
        assert "NEXUS IDE" in response.text
        print("✅ Frontend load: OK")
        return True
    except Exception as e:
        print(f"❌ Frontend load: FALHOU - {e}")
        return False

def test_chat_endpoint():
    """Testa endpoint de chat."""
    try:
        response = requests.post(
            "http://localhost:8000/api/v1/chat",
            json={"message": "test", "agent": "coder"},
            timeout=10
        )
        # Pode falhar se LLM providers estiverem down
        if response.status_code == 200:
            print("✅ Chat endpoint: OK")
            return True
        else:
            print(f"⚠️ Chat endpoint: Status {response.status_code} (providers podem estar down)")
            return False
    except Exception as e:
        print(f"⚠️ Chat endpoint: {e}")
        return False

def test_critical_pages():
    """Testa páginas críticas."""
    pages = ["/dashboard", "/chat", "/mission-control"]
    all_ok = True
    
    for page in pages:
        try:
            response = requests.get(f"http://localhost:3000{page}", timeout=5)
            if response.status_code == 200:
                print(f"✅ {page}: OK")
            else:
                print(f"❌ {page}: Status {response.status_code}")
                all_ok = False
        except Exception as e:
            print(f"❌ {page}: {e}")
            all_ok = False
    
    return all_ok

if __name__ == "__main__":
    print("=" * 60)
    print("TESTE DE INTEGRIDADE - NEXUS IDE")
    print("=" * 60)
    
    results = []
    results.append(("Backend Health", test_backend_health()))
    results.append(("Frontend Load", test_frontend_loads()))
    results.append(("Chat Endpoint", test_chat_endpoint()))
    results.append(("Critical Pages", test_critical_pages()))
    
    print("
" + "=" * 60)
    print("RESUMO")
    print("=" * 60)
    
    for name, result in results:
        status = "✅ PASSOU" if result else "❌ FALHOU"
        print(f"{name:20s}: {status}")
    
    # Exit code baseado em resultados
    all_passed = all(result for _, result in results)
    sys.exit(0 if all_passed else 1)
