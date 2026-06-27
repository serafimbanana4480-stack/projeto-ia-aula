"use client";

import { useEffect, useState } from 'react';

export function DashboardPro() {
  const [metrics, setMetrics] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Simular dados de sistema (funciona sem backend)
    setTimeout(() => {
      setMetrics({
        cpu: 42,
        memory: 68,
        storage: 92,
        uptime: '15.2h',
        model: 'MockLLM (Dev Mode)',
        providers: [
          { name: 'MockLLM', status: 'up', latency: '45ms' },
          { name: 'OpenCode Go', status: 'down', latency: '-' },
        ]
      });
      setLoading(false);
    }, 500);
  }, []);

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
        <div style={{ border: '4px solid #7c6afb', borderTop: '4px solid transparent', borderRadius: '50%', width: '40px', height: '40px', animation: 'spin 1s linear infinite' }}></div>
      </div>
    );
  }

  return (
    <div style={{ padding: '24px', color: 'white' }}>
      <h1 style={{ fontSize: '28px', fontWeight: 'bold', marginBottom: '8px' }}>Dashboard</h1>
      <p style={{ color: '#9ca3af', marginBottom: '24px' }}>Visão geral do sistema (Modo Desenvolvimento)</p>

      {/* Métricas */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
        <div style={{ backgroundColor: '#1a1a2e', padding: '16px', borderRadius: '8px', border: '1px solid #2d2d44' }}>
          <p style={{ color: '#9ca3af', fontSize: '14px' }}>CPU</p>
          <p style={{ fontSize: '24px', fontWeight: 'bold' }}>{metrics.cpu}%</p>
          <div style={{ backgroundColor: '#0b0b14', height: '8px', borderRadius: '4px', marginTop: '8px' }}>
            <div style={{ backgroundColor: '#3b82f6', height: '100%', width: `${metrics.cpu}%`, borderRadius: '4px' }}></div>
          </div>
        </div>

        <div style={{ backgroundColor: '#1a1a2e', padding: '16px', borderRadius: '8px', border: '1px solid #2d2d44' }}>
          <p style={{ color: '#9ca3af', fontSize: '14px' }}>Memória</p>
          <p style={{ fontSize: '24px', fontWeight: 'bold' }}>{metrics.memory}%</p>
          <div style={{ backgroundColor: '#0b0b14', height: '8px', borderRadius: '4px', marginTop: '8px' }}>
            <div style={{ backgroundColor: '#10b981', height: '100%', width: `${metrics.memory}%`, borderRadius: '4px' }}></div>
          </div>
        </div>

        <div style={{ backgroundColor: '#1a1a2e', padding: '16px', borderRadius: '8px', border: '1px solid #2d2d44' }}>
          <p style={{ color: '#9ca3af', fontSize: '14px' }}>Armazenamento</p>
          <p style={{ fontSize: '24px', fontWeight: 'bold' }}>{metrics.storage}%</p>
          <div style={{ backgroundColor: '#0b0b14', height: '8px', borderRadius: '4px', marginTop: '8px' }}>
            <div style={{ backgroundColor: '#f59e0b', height: '100%', width: `${metrics.storage}%`, borderRadius: '4px' }}></div>
          </div>
        </div>

        <div style={{ backgroundColor: '#1a1a2e', padding: '16px', borderRadius: '8px', border: '1px solid #2d2d44' }}>
          <p style={{ color: '#9ca3af', fontSize: '14px' }}>Uptime</p>
          <p style={{ fontSize: '24px', fontWeight: 'bold' }}>{metrics.uptime}</p>
          <p style={{ color: '#9ca3af', fontSize: '12px', marginTop: '8px' }}>Modelo: {metrics.model}</p>
        </div>
      </div>

      {/* Status Providers */}
      <div style={{ backgroundColor: '#1a1a2e', padding: '16px', borderRadius: '8px', border: '1px solid #2d2d44', marginBottom: '24px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: '600', marginBottom: '12px' }}>Estado dos Providers LLM</h2>
        {metrics.providers.map((p: any, i: number) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px', backgroundColor: '#0b0b14', borderRadius: '8px', marginBottom: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div style={{ width: '12px', height: '12px', borderRadius: '50%', backgroundColor: p.status === 'up' ? '#10b981' : '#ef4444' }}></div>
              <span>{p.name}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              <span style={{ 
                padding: '4px 8px', 
                borderRadius: '4px', 
                fontSize: '12px',
                backgroundColor: p.status === 'up' ? '#10b98120' : '#ef444420',
                color: p.status === 'up' ? '#10b981' : '#ef4444'
              }}>
                {p.status === 'up' ? 'Online' : 'Offline'}
              </span>
              <span style={{ color: '#9ca3af', fontSize: '14px' }}>{p.latency}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Ações */}
      <div style={{ display: 'flex', gap: '12px' }}>
        <button 
          onClick={() => window.location.href = '/chat'}
          style={{ 
            backgroundColor: '#7c6afb', 
            color: 'white', 
            padding: '8px 16px', 
            borderRadius: '6px', 
            border: 'none', 
            cursor: 'pointer',
            fontSize: '14px'
          }}
        >
          💬 Novo Chat
        </button>
        <button 
          onClick={() => window.location.reload()}
          style={{ 
            backgroundColor: 'transparent', 
            color: 'white', 
            padding: '8px 16px', 
            borderRadius: '6px', 
            border: '1px solid #2d2d44', 
            cursor: 'pointer',
            fontSize: '14px'
          }}
        >
          🔄 Atualizar
        </button>
      </div>
    </div>
  );
}
