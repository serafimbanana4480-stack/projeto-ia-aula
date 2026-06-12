import sys
sys.path.insert(0, 'backend')

from fastapi.testclient import TestClient
from orchestrator.main import app
client = TestClient(app)

# Get token
r = client.post('/api/auth/login', json={'email': 'test_audit@example.com', 'password': 'testpass123'})
if r.status_code != 200:
    r = client.post('/api/auth/register', json={'email': 'test_audit@example.com', 'password': 'testpass123'})
    r = client.post('/api/auth/login', json={'email': 'test_audit@example.com', 'password': 'testpass123'})

token = r.json().get('access_token', '')
headers = {'Authorization': f'Bearer {token}'}

print('=== TESTS WITH AUTH ===')
print(f'Token: {token[:20]}...')
print()

# More endpoints
endpoints = [
    ('GET', '/api/projects', None),
    ('GET', '/api/workers', None),
    ('GET', '/api/settings', None),
    ('GET', '/api/modes', None),
    ('GET', '/api/system', None),
    ('GET', '/api/metrics', None),
    ('GET', '/api/metrics/current', None),
    ('GET', '/api/metrics/history', None),
    ('POST', '/api/chat', {'message': 'hello', 'session_id': 'test', 'mode': 'fast'}),
    ('POST', '/api/plan', {'query': 'test plan'}),
    ('GET', '/api/missions', None),
    ('POST', '/api/web_search', {'query': 'python programming'}),
    ('GET', '/api/db/stats', None),
    ('GET', '/api/alerts/current', None),
    ('GET', '/api/bus/topics', None),
    ('GET', '/api/agent-states', None),
    ('GET', '/api/skills', None),
    ('GET', '/api/overseer/status', None),
    ('GET', '/api/guardian/status', None),
    ('POST', '/api/embeddings/index', {'paths': ['README.md']}),
]

for method, path, body in endpoints:
    try:
        if method == 'GET':
            r = client.get(path, headers=headers)
        else:
            r = client.post(path, json=body, headers=headers)
        status = r.status_code
        text = r.text[:80]
        print(f'  {method:4} {path:40} {status:3} -> {text}')
    except Exception as e:
        print(f'  {method:4} {path:40} ERR -> {str(e)[:80]}')

print()
print('=== ENDPOINTS SEM AUTH (publicos) ===')
public = ['/health', '/api/modes', '/api/models/status']
for path in public:
    r = client.get(path)
    print(f'  GET  {path:40} {r.status_code} -> {r.text[:60]}')
