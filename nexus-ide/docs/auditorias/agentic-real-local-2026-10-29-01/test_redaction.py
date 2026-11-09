import sys
sys.path.insert(0, 'C:\\Users\\rodri\\Desktop\\nexus\\nexus-ide')
from redaction import is_sensitive_file_request

def test_git_credentials_is_sensitive():
    assert is_sensitive_file_request({'path': '.git-credentials'})
