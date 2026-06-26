"""Integration tests for knowledge/memory API endpoints."""
from __future__ import annotations


def test_get_knowledge_stats(client):
    """Test GET /api/knowledge/stats endpoint."""
    response = client.get("/api/knowledge/stats")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "collections" in data
    assert "entities" in data
    assert "relations" in data
    assert "documents" in data
    assert "embeddings" in data
    
    # Verify data types
    assert isinstance(data["collections"], int)
    assert isinstance(data["entities"], int)
    assert isinstance(data["relations"], int)
    assert isinstance(data["documents"], int)
    assert isinstance(data["embeddings"], int)


def test_get_memory_stats(client):
    """Test GET /api/memory/stats endpoint."""
    response = client.get("/api/memory/stats")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "semantic" in data
    assert "episodic" in data
    assert "vector" in data
    assert "graph" in data
    assert "procedural" in data
    
    # Verify semantic memory structure
    assert "count" in data["semantic"]
    assert "size" in data["semantic"]
    
    # Verify episodic memory structure
    assert "count" in data["episodic"]
    assert "size" in data["episodic"]
    
    # Verify vector memory structure
    assert "count" in data["vector"]
    assert "size" in data["vector"]
    
    # Verify graph memory structure
    assert "nodes" in data["graph"]
    assert "edges" in data["graph"]
    
    # Verify procedural memory structure
    assert "count" in data["procedural"]
    assert "size" in data["procedural"]
    
    # Verify data types
    assert isinstance(data["semantic"]["count"], int)
    assert isinstance(data["semantic"]["size"], int)
