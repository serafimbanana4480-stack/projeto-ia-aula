import sys, json
sys.path.insert(0, 'backend')

from fastapi.testclient import TestClient
from orchestrator.main import app
client = TestClient(app)

print('=== TEST 1: HEALTH ===')
r = client.get('/health')
print(f'  /health: {r.status_code} -> {r.json() if r.status_code==200 else r.text[:100]}')

r = client.get('/health?deep=true')
print(f'  /health?deep: {r.status_code} -> {r.text[:100]}')

print()
print('=== TEST 2: FILE API ===')
r = client.post('/api/files/read', json={'path': 'README.md'})
print(f'  read README.md: {r.status_code}')
if r.status_code == 200:
    data = r.json()
    print(f'    content length: {len(data.get("content", ""))}')

r = client.post('/api/files/list', json={'path': '.'})
print(f'  list root: {r.status_code}')
if r.status_code == 200:
    data = r.json()
    print(f'    items: {len(data.get("items", []))}')

print()
print('=== TEST 3: SHELL ===')
r = client.post('/api/terminal/execute', json={'command': 'echo hello_nexus', 'project_path': '.'})
print(f'  echo: {r.status_code}')
if r.status_code == 200:
    print(f'    stdout: {r.json().get("stdout", "").strip()[:50]}')

r = client.post('/api/terminal/execute', json={'command': 'python --version', 'project_path': '.'})
print(f'  python --version: {r.status_code}')
if r.status_code == 200:
    print(f'    stdout: {r.json().get("stdout", "").strip()[:50]}')

print()
print('=== TEST 4: EMBEDDINGS/RAG ===')
r = client.post('/api/embeddings/index', json={'paths': ['README.md']})
print(f'  index README: {r.status_code} -> {r.text[:100]}')

r = client.get('/api/embeddings/search?q=test')
print(f'  search: {r.status_code} -> {r.text[:100]}')

print()
print('=== TEST 5: MODELS ===')
r = client.get('/api/models/status')
print(f'  models/status: {r.status_code} -> {r.text[:100]}')

print()
print('=== TEST 6: MODES ===')
r = client.get('/api/modes')
print(f'  /modes: {r.status_code} -> {r.text[:100]}')

print()
print('=== TEST 7: DASHBOARD ===')
r = client.get('/api/dashboard/status')
print(f'  dashboard/status: {r.status_code} -> {r.text[:100]}')

r = client.get('/api/dashboard/metrics')
print(f'  dashboard/metrics: {r.status_code} -> {r.text[:100]}')

print('=== TEST 8: AUTH ===')
r = client.post('/api/auth/register', json={'email': 'test_audit@example.com', 'password': 'testpass123'})
print(f'  register: {r.status_code} -> {r.text[:100]}')

r = client.post('/api/auth/login', json={'email': 'test_audit@example.com', 'password': 'testpass123'})
print(f'  login: {r.status_code} -> {r.text[:100]}')
if r.status_code == 200:
    token = r.json().get('access_token', '')
    print(f'    token: {token[:20]}...' if token else '    NO TOKEN')
    
    # Test with auth
    headers = {'Authorization': f'Bearer {token}'}
    
    print()
    print('=== TEST 9: FILE API WITH AUTH ===')
    r = client.post('/api/files/read', json={'path': 'README.md'}, headers=headers)
    print(f'  read README: {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        print(f'    content length: {len(data.get("content", ""))}')
    elif r.status_code != 200:
        print(f'    error: {r.text[:100]}')
    
    r = client.post('/api/files/list', json={'path': '.'}, headers=headers)
    print(f'  list root: {r.status_code}')
    if r.status_code == 200:
        data = r.json()
        print(f'    items: {len(data.get("items", []))}')
    
    print()
    print('=== TEST 10: SHELL WITH AUTH ===')
    r = client.post('/api/terminal/execute', json={'command': 'echo hello_nexus', 'project_path': '.'}, headers=headers)
    print(f'  echo: {r.status_code}')
    if r.status_code == 200:
        print(f'    stdout: {r.json().get("stdout", "").strip()[:50]}')
    elif r.status_code != 200:
        print(f'    error: {r.text[:100]}')
    
    print()
    print('=== TEST 11: DASHBOARD WITH AUTH ===')
    r = client.get('/api/dashboard/status', headers=headers)
    print(f'  dashboard/status: {r.status_code} -> {r.text[:100]}')
    
    r = client.get('/api/dashboard/metrics', headers=headers)
    print(f'  dashboard/metrics: {r.status_code} -> {r.text[:100]}')
    
    print()
    print('=== TEST 12: PATH TRAVERSAL TEST ===')
    r = client.post('/api/files/read', json={'path': '../../../etc/passwd', 'project_path': '.'}, headers=headers)
    print(f'  path traversal: {r.status_code} -> {r.text[:100]}')
    
    print()
    print('=== TEST 13: COMMAND INJECTION TEST ===')
    r = client.post('/api/terminal/execute', json={'command': 'echo hello; rm -rf /', 'project_path': '.'}, headers=headers)
    print(f'  injection attempt: {r.status_code} -> {r.text[:100]}')
    
    print()
    print('=== TEST 14: PYTHON SANDBOX TEST ===')
    r = client.post('/api/terminal/execute', json={'command': 'python -c "import os; print(os.system(\'whoami\'))"', 'project_path': '.'}, headers=headers)
    print(f'  python sandbox: {r.status_code} -> {r.text[:100]}')

print()
print('=== TEST 15: PROJECTS ===')
r = client.get('/api/projects')
print(f'  /projects: {r.status_code} -> {r.text[:100]}')

print()
print('=== TEST 16: CHAT ===')
r = client.post('/api/chat', json={'message': 'hello', 'session_id': 'test'})
print(f'  /chat: {r.status_code} -> {r.text[:100]}')
