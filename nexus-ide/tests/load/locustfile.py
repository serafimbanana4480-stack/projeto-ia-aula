
"""
Load Testing - Testa performance sob carga.
"""
from locust import HttpUser, task, between

class NEXUSIDEUser(HttpUser):
    """Simula utilizadores reais."""
    
    wait_time = between(1, 3)
    
    @task(3)
    def view_dashboard(self):
        """Acede dashboard."""
        self.client.get("/dashboard")
        
    @task(2)
    def send_chat_message(self):
        """Envia mensagem no chat."""
        self.client.post("/api/v1/chat", json={
            "message": "Olá, teste de carga!",
            "agent": "coder",
        })
        
    @task(1)
    def view_mission_control(self):
        """Acede Mission Control."""
        self.client.get("/mission-control")
