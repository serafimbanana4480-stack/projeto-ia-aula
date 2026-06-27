
// Sistema de Ajuda Contextual
// Mostra ajuda relevante baseada no que o utilizador está a fazer
'use client';

import { useState, useEffect } from 'react';
import { Card } from '@/components/ui/card';

interface ContextualHelpProps {
  currentView: string;
}

export function ContextualHelp({ currentView }: ContextualHelpProps) {
  const [help, setHelp] = useState<any>(null);
  const [dismissed, setDismissed] = useState(false);
  
  useEffect(() => {
    // Buscar ajuda baseada na vista atual
    fetch(`/api/v1/help?context=${currentView}`)
      .then(res => res.json())
      .then(data => {
        setHelp(data);
        setDismissed(false);
      });
  }, [currentView]);
  
  if (!help || dismissed) return null;
  
  return (
    <Card className="p-4 mb-4 border-blue-200 bg-blue-50">
      <div className="flex justify-between items-start">
        <div>
          <h3 className="font-semibold text-blue-900">💡 {help.title}</h3>
          <p className="text-sm text-blue-800 mt-1">{help.content}</p>
          
          {help.shortcuts && help.shortcuts.length > 0 && (
            <div className="mt-2">
              <strong className="text-xs text-blue-700">Atalhos:</strong>
              <ul className="text-xs text-blue-600 mt-1">
                {help.shortcuts.map((shortcut: string, i: number) => (
                  <li key={i}>{shortcut}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
        
        <button
          onClick={() => setDismissed(true)}
          className="text-blue-500 hover:text-blue-700"
        >
          ✕
        </button>
      </div>
    </Card>
  );
}
