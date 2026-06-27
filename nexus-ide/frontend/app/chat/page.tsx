// @ts-nocheck
"use client";

import { useState } from 'react';

export default function ChatPage() {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Olá! Sou o MockLLM do NEXUS IDE. Como posso ajudar?' }
  ]);
  const [input, setInput] = useState('');

  const handleSend = () => {
    if (!input.trim()) return;

    // Adicionar mensagem do utilizador
    const userMessage = { role: 'user', content: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');

    // Simular resposta do MockLLM (1 segundo delay)
    setTimeout(() => {
      const mockResponse = {
        role: 'assistant',
        content: `Entendi: "${input}". Esta é uma resposta simulada do MockLLM. Para usar o LLM real, configure a API key no ficheiro .env.`
      };
      setMessages(prev => [...prev, mockResponse]);
    }, 1000);
  };

  return (
    <div style={{ 
      display: 'flex', 
      flexDirection: 'column', 
      height: '100vh',
      maxWidth: '1200px',
      margin: '0 auto',
      padding: '24px'
    }}>
      <h1 style={{ fontSize: '24px', fontWeight: 'bold', marginBottom: '16px', color: 'white' }}>
        💬 Chat - NEXUS IDE
      </h1>
      <p style={{ color: '#9ca3af', marginBottom: '24px' }}>
        Interface de chat com MockLLM (Modo Desenvolvimento)
      </p>
      
      {/* Área de Mensagens */}
      <div style={{ 
        flex: 1,
        backgroundColor: '#1a1a2e', 
        borderRadius: '8px', 
        padding: '16px',
        overflowY: 'auto',
        marginBottom: '16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px'
      }}>
        {messages.map((msg, index) => (
          <div 
            key={index}
            style={{ 
              backgroundColor: msg.role === 'user' ? '#7c6afb20' : '#0b0b14',
              padding: '12px', 
              borderRadius: '8px',
              alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
              maxWidth: '80%'
            }}
          >
            <p style={{ 
              color: '#7c6afb', 
              fontSize: '12px', 
              marginBottom: '4px',
              fontWeight: '600'
            }}>
              {msg.role === 'user' ? 'Tu' : 'MockLLM'}
            </p>
            <p style={{ color: 'white', lineHeight: '1.5' }}>{msg.content}</p>
          </div>
        ))}
      </div>
      
      {/* Input de Mensagem */}
      <div style={{ 
        display: 'flex',
        gap: '8px'
      }}>
        <input 
          type="text" 
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Escreve uma mensagem..." 
          style={{
            flex: 1,
            padding: '12px',
            backgroundColor: '#1a1a2e',
            border: '1px solid #2d2d44',
            borderRadius: '8px',
            color: 'white',
            fontSize: '14px'
          }}
        />
        <button 
          onClick={handleSend}
          style={{
            padding: '12px 24px',
            backgroundColor: '#7c6afb',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: 'pointer',
            fontWeight: '600',
            fontSize: '14px'
          }}
        >
          Enviar
        </button>
      </div>
    </div>
  );
}
