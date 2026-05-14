#!/usr/bin/env python3
"""Configuration validation script for NEXUS IDE.

Validates that all required environment variables are set and have valid values.
"""
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config.settings import get_settings


def validate_config() -> bool:
    """Validate configuration settings."""
    print("🔍 Validating NEXUS IDE configuration...")
    
    try:
        settings = get_settings()
        print("✅ Settings loaded successfully")
    except Exception as e:
        print(f"❌ Failed to load settings: {e}")
        return False
    
    # Validate critical settings
    errors = []
    
    # Check Ollama configuration
    if not settings.ollama_host:
        errors.append("OLLAMA_HOST is not set")
    else:
        print(f"✅ OLLAMA_HOST: {settings.ollama_host}")
    
    if not settings.ollama_dashboard_host:
        errors.append("OLLAMA_DASHBOARD_HOST is not set")
    else:
        print(f"✅ OLLAMA_DASHBOARD_HOST: {settings.ollama_dashboard_host}")
    
    # Check Redis configuration
    if not settings.redis_url:
        errors.append("REDIS_URL is not set")
    else:
        print(f"✅ REDIS_URL: {settings.redis_url}")
    
    # Check backend configuration
    if not settings.backend_host:
        errors.append("BACKEND_HOST is not set")
    else:
        print(f"✅ BACKEND_HOST: {settings.backend_host}")
    
    if not settings.backend_port:
        errors.append("BACKEND_PORT is not set")
    else:
        print(f"✅ BACKEND_PORT: {settings.backend_port}")
    
    # Check observability configuration
    if not settings.otel_exporter_otlp_endpoint:
        errors.append("OTEL_EXPORTER_OTLP_ENDPOINT is not set")
    else:
        print(f"✅ OTEL_EXPORTER_OTLP_ENDPOINT: {settings.otel_exporter_otlp_endpoint}")
    
    # Check if .env file exists
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        errors.append(".env file does not exist (copy from .env.example)")
    else:
        print(f"✅ .env file exists")
    
    # Check if data directory exists
    data_dir = Path(__file__).parent.parent / "data"
    if not data_dir.exists():
        print(f"⚠️  Data directory does not exist, creating it...")
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"✅ Data directory created: {data_dir}")
    else:
        print(f"✅ Data directory exists: {data_dir}")
    
    if errors:
        print("\n❌ Configuration validation failed:")
        for error in errors:
            print(f"   - {error}")
        return False
    
    print("\n✅ All configuration validations passed!")
    return True


if __name__ == "__main__":
    success = validate_config()
    sys.exit(0 if success else 1)