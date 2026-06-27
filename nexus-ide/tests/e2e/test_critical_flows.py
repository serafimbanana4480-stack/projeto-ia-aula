
"""
E2E Test Suite - Testa todos os fluxos críticos da aplicação.
"""
import pytest
from playwright.sync_api import Page, expect

class TestCriticalFlows:
    """Testes E2E para fluxos críticos."""
    
    def test_login(self, page: Page):
        """Testa fluxo de login."""
        page.goto("http://localhost:3000")
        
        # Verificar se está na página de login ou já autenticado
        if page.locator("text=Login").is_visible():
            page.fill("#username", "admin")
            page.fill("#password", "admin123")
            page.click("button:has-text('Login')")
            
        # Verificar redirecionamento para dashboard
        expect(page).to_have_url("http://localhost:3000/dashboard")
        
    def test_chat_functionality(self, page: Page):
        """Testa funcionalidade de chat."""
        page.goto("http://localhost:3000/chat")
        
        # Enviar mensagem
        page.fill("textarea[placeholder*='Pergunte']", "Olá, teste automático!")
        page.click("button[type='submit']")
        
        # Verificar se resposta aparece
        expect(page.locator("text=CODER")).to_be_visible(timeout=10000)
        
    def test_dashboard_loads(self, page: Page):
        """Testa se dashboard carrega corretamente."""
        page.goto("http://localhost:3000/dashboard")
        
        # Verificar elementos críticos
        expect(page.locator("text=Agentic Hub")).to_be_visible()
        expect(page.locator("text=Estado do Sistema")).to_be_visible()
        
    def test_mission_control(self, page: Page):
        """Testa Mission Control."""
        page.goto("http://localhost:3000/mission-control")
        
        # Verificar se carrega
        expect(page.locator("text=Mission Control")).to_be_visible()
