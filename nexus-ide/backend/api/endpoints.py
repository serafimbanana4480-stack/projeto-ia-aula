
"""
API de Conectividade - Testa comunicação Backend ↔ Frontend.
"""
from fastapi import APIRouter, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any

router = APIRouter()

@router.get("/api/v1/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat(),
    }

@router.get("/api/v1/dashboard")
async def get_dashboard_data() -> Dict[str, Any]:
    """Retorna dados para o Dashboard."""
    return {
        "systemStatus": "healthy",
        "activeModel": "OpenCode Go (Claude 3.5 Sonnet)",
        "cpuUsage": 45.3,
        "memoryUsage": 55.7,
        "storageUsage": 91.8,
        "agentsConnected": 8,
        "messagesProcessed": 1247,
        "uptime": "14.9h",
    }

@router.post("/api/v1/chat")
async def chat_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Endpoint de chat com fallback chain."""
    from backend.llm.fallback_chain import llm_chain
    
    try:
        response = llm_chain.call(payload.get("message", ""))
        return {
            "success": True,
            "content": response.get("content", ""),
            "model": response.get("model", "unknown"),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }

@router.get("/api/v1/providers/status")
async def get_providers_status() -> Dict[str, Any]:
    """Retorna status dos providers LLM."""
    from backend.llm.fallback_chain import llm_chain
    
    status = llm_chain.test_all_providers()
    return {"providers": status}
