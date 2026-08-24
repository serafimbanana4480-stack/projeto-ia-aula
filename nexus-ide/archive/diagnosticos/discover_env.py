import os
import json
import subprocess
import sys
from pathlib import Path

project_root = Path.cwd()

# Function to safely list directory contents
def safe_list_dir(path):
    try:
        return [f.name for f in path.iterdir()]
    except PermissionError:
        return []

# Build directory tree (limited depth for brevity)
def build_tree(path, max_depth=3, current_depth=0):
    if current_depth >= max_depth:
        return {'name': path.name, 'type': 'directory', 'children': []}
    
    node = {'name': path.name, 'type': 'directory', 'children': []}
    try:
        for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            # Skip hidden and common build directories
            if item.name.startswith('.') and item.name not in ['.env', '.env.example']:
                continue
            if item.name in ['__pycache__', '.git', '.mypy_cache', '.pytest_cache', 'node_modules', 'dist', 'build']:
                continue
            
            if item.is_dir():
                node['children'].append(build_tree(item, max_depth, current_depth + 1))
            else:
                node['children'].append({'name': item.name, 'type': 'file', 'size': item.stat().st_size})
    except PermissionError:
        pass
    return node

# Get installed packages
def get_installed_packages():
    try:
        # Try using uv first
        result = subprocess.run(['uv', 'pip', 'list', '--format', 'json'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except:
        pass
    
    try:
        # Fallback to pip
        result = subprocess.run([sys.executable, '-m', 'pip', 'list', '--format', 'json'],
                              capture_output=True, text=True, timeout= True:
        if result.returncode == 0:
            return json.loads(result.stdout)
    except:
        pass
    return []

10)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except:
        pass
    return []

# Find configuration files
def find_config_files(root, max_depth=2):
    config_files = []
    config_patterns = ['*.env', '*.env.*', '*.ini', '*.cfg', '*.conf', '*.yaml', '*.yml', '*.json', '*.toml', '*.xml', '*.properties']
    
    def _search(path, depth):
        if depth > max_depth:
            return
        try:
            for item in path.iterdir():
                if item.is_dir():
                    if not item.name.startswith('.') and item.name not in ['__pycache__', '.git', 'node_modules']:
                        _search(item, depth + 1)
                else:
                    for pattern in config_patterns:
                        if item.match(pattern):
                            config_files.append(str(item.relative_to(root)))
                            break
        except PermissionError:
            pass
    
    _search(root, 0)
    return config_files

# Get environment variables
def get_environment():
    # Get system environment variables
    env = dict(os.environ)
    # Try to load .env file if exists
    env_file = project_root / '.env'
    if env_file.exists():
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env[f'DOTENV_{key}'] = value.strip('"\'')
        except:
            pass
    return env

# Build inventory
inventory = {
    'project_root': str(project_root),
    'directory_tree': build_tree(project_root),
    'installed_packages': get_installed_packages(),
    'configuration_files': find_config_files(project_root),
    'environment_variables': get_environment(),
    'inventory_timestamp': str(os.datetime.now()) if hasattr(os, 'datetime') else 'unknown'
}

# Write to /tmp/nexus_env_inventory.json
output_path = '/tmp/nexus_env_inventory.json'
try:
    with open(output_path, 'w') as f:
        json.dump(inventory, f, indent=2, default=str)
    print(f"Inventory written to {output_path}")
except Exception as e:
    print(f"Error writing to {output_path}: {e}")
    # Try fallback to project temp
    fallback = project_root / 'tmp' / 'nexus_env_inventory.json'
    fallback.parent.mkdir(exist_ok=True)
    with open(fallback, 'w') as f:
        json.dump(inventory, f, indent=2, default=str)
    print(f"Inventory written to fallback: {fallback}")
