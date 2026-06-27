// @ts-nocheck
"use client";

export default function DashboardPage() {
  return (
    <div style={{ padding: '24px', color: 'white' }}>
      <h1 style={{ fontSize: '28px', fontWeight: 'bold', marginBottom: '16px' }}>
        📊 Dashboard - NEXUS IDE
      </h1>
      <p style={{ color: '#9ca3af', marginBottom: '24px' }}>
        Sistema Operacional (Modo Desenvolvimento)
      </p>

      {/* Métricas */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', 
        gap: '16px',
        marginBottom: '24px'
      }}>
        <div style={{ backgroundColor: '#1a1a2e', padding: '20px', borderRadius: '8px' }}>
          <p style={{ color: '#9ca3af', fontSize: '14px', marginBottom: '8px' }}>CPU</p>
          <p style={{ fontSize: '32px', fontWeight: 'bold' }}>45%</p>
          <div style={{ backgroundColor: '#0b0b14', height: '8px', borderRadius: '4px', marginTop: '12px' }}>
            <div style={{ backgroundColor: '#3b82f6', height: '100%', width: '45%', borderRadius: '4px' }}></div>
          </div>
        </div>
        
        <div style={{ backgroundColor: '#1a1a2e', padding: '20px', borderRadius: '8px' }}>
          <p style={{ color: '#9ca3af', fontSize: '14px', marginBottom: '8px' }}>Memória</p>
          <p style={{ fontSize: '32px', fontWeight: 'bold' }}>62%</p>
          <div style={{ backgroundColor: '#0b0b14', height: '8px', borderRadius: '4px', marginTop: '12px' }}>
            <div style={{ backgroundColor: '#10b981', height: '100%', width: '62%', borderRadius: '4px' }}></div>
          </div>
        </div>
        
        <div style={{ backgroundColor: '#1a1a2e', padding: '20px', borderRadius: '8px' }}>
          <p style={{ color: '#9ca3af', fontSize: '14px', marginBottom: '8px' }}>Armazenamento</p>
          <p style={{ fontSize: '32px', fontWeight: 'bold' }}>92%</p>
          <div style={{ backgroundColor: '#0b0b14', height: '8px', borderRadius: '4px', marginTop: '12px' }}>
            <div style={{ backgroundColor: '#f59e0b', height: '100%', width: '92%', borderRadius: '4px' }}></div>
          </div>
        </div>
        
        <div style={{ backgroundColor: '#1a1a2e', padding: '20px', borderRadius: '8px' }}>
          <p style={{ color: '#9ca3af', fontSize: '14px', marginBottom: '8px' }}>Uptime</p>
          <p style={{ fontSize: '32px', fontWeight: 'bold' }}>15.2h</p>
          <p style={{ color: '#9ca3af', fontSize: '12px', marginTop: '12px' }}>Modelo: MockLLM</p>
        </div>
      </div>

      {/* Status Providers */}
      <div style={{ backgroundColor: '#1a1a2e', padding: '20px', borderRadius: '8px', marginBottom: '24px' }}>
        <h2 style={{ fontSize: '20px', fontWeight: '600', marginBottom: '16px' }}>
          Estado dos Providers LLM
        </h2>
        
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', 
                      padding: '12px', backgroundColor: '#0b0b14', borderRadius: '8px', marginBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '12px', height: '12px', borderRadius: '50%', backgroundColor: '#10b981' }}></div>
            <span style={{ fontWeight: '500' }}>MockLLM (Dev Mode)</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <span style={{ 
              padding: '4px 12px', 
              borderRadius: '4px', 
              fontSize: '12px',
              backgroundColor: '#10b98120',
              color: '#10b981',
              fontWeight: '600'
            }}>
              Online
            </span>
            <span style={{ color: '#9ca3af', fontSize: '14px' }}>45ms</span>
          </div>
        </div>
        
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', 
                      padding: '12px', backgroundColor: '#0b0b14', borderRadius: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '12px', height: '12px', borderRadius: '50%', backgroundColor: '#ef4444' }}></div>
            <span style={{ fontWeight: '500' }}>OpenCode Go</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <span style={{ 
              padding: '4px 12px', 
              borderRadius: '4px', 
              fontSize: '12px',
              backgroundColor: '#ef444420',
              color: '#ef4444',
              fontWeight: '600'
            }}>
              Offline
            </span>
            <span style={{ color: '#9ca3af', fontSize: '14px' }}>Precisa API key</span>
          </div>
        </div>
      </div>

      {/* Ações */}
      <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
        <button 
          onClick={() => window.location.href = '/chat'}
          style={{ 
            backgroundColor: '#7c6afb', 
            color: 'white', 
            padding: '12px 24px', 
            borderRadius: '8px', 
            border: 'none', 
            cursor: 'pointer',
            fontSize: '14px',
            fontWeight: '600'
          }}
        >
          💬 Ir para Chat
        </button>
        
        <button 
          onClick={() => window.location.reload()}
          style={{ 
            backgroundColor: 'transparent', 
            color: 'white', 
            padding: '12px 24px', 
            borderRadius: '8px', 
            border: '1px solid #2d2d44', 
            cursor: 'pointer',
            fontSize: '14px'
          }}
        >
          🔄 Atualizar Dados
        </button>
        
        <button 
          onClick={() => window.open('http://localhost:8000/docs', '_blank')}
          style={{ 
            backgroundColor: 'transparent', 
            color: 'white', 
            padding: '12px 24px', 
            borderRadius: '8px', 
            border: '1px solid #2d2d44', 
            cursor: 'pointer',
            fontSize: '14px'
          }}
        >
          📚 Documentação API
        </button>
      </div>
    </div>
  );
}
