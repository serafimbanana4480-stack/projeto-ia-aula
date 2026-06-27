"use client";

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

export function SidebarPro() {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  const navigation = [
    { name: 'Dashboard', href: '/dashboard', icon: '📊' },
    { name: 'Chat', href: '/chat', icon: '💬' },
    { name: 'Mission Control', href: '/mission-control', icon: '🎯' },
    { name: 'Configurações', href: '/settings', icon: '⚙️' },
    { name: 'Ajuda', href: '/help', icon: '❓' },
  ];

  return (
    <div
      style={{
        height: '100vh',
        width: collapsed ? '64px' : '256px',
        backgroundColor: '#1a1a2e',
        borderRight: '1px solid #2d2d44',
        display: 'flex',
        flexDirection: 'column',
        transition: 'width 0.3s',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          height: '64px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'space-between',
          padding: '0 16px',
          borderBottom: '1px solid #2d2d44',
        }}
      >
        {!collapsed && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '24px' }}>⚡</span>
            <span style={{ fontSize: '20px', fontWeight: 'bold', color: 'white' }}>NEXUS</span>
          </div>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          style={{
            background: 'none',
            border: 'none',
            color: '#9ca3af',
            cursor: 'pointer',
            fontSize: '16px',
          }}
        >
          {collapsed ? '▶' : '◀'}
        </button>
      </div>

      {/* Navigation */}
      <nav style={{ flex: 1, padding: '16px 8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {navigation.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.name}
              href={item.href}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                padding: '8px 12px',
                borderRadius: '8px',
                textDecoration: 'none',
                color: isActive ? 'white' : '#9ca3af',
                backgroundColor: isActive ? '#7c6afb' : 'transparent',
                fontSize: '14px',
                fontWeight: isActive ? '600' : '400',
                transition: 'background-color 0.2s',
              }}
            >
              <span style={{ fontSize: '18px' }}>{item.icon}</span>
              {!collapsed && <span>{item.name}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Status */}
      {!collapsed && (
        <div style={{ padding: '16px', borderTop: '1px solid #2d2d44' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#10b981', fontSize: '13px' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#10b981' }}></div>
            <span>Sistema Operacional</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#6b7280', fontSize: '12px', marginTop: '4px' }}>
            <span>🤖</span>
            <span>MockLLM Ativo</span>
          </div>
        </div>
      )}
    </div>
  );
}
