"""
Main API Router - Centralizes all API endpoints.
"""
from fastapi import APIRouter
from backend.api import auth, agents, chat, dashboard

api_router = APIRouter(prefix="/api/v1")

# Include all sub-routers
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(agents.router, prefix="/agents", tags=["Agents"])
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])

@api_router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}
