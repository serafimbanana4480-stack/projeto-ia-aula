
// Componente de Feedback em Tempo Real
// Permite ao utilizador dar feedback e melhora a IA
'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

interface FeedbackWidgetProps {
  agentName?: string;
  messageId?: string;
}

export function FeedbackWidget({ agentName, messageId }: FeedbackWidgetProps) {
  const [feedback, setFeedback] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [rating, setRating] = useState(0);
  
  const handleSubmit = async () => {
    if (!feedback.trim()) return;
    
    // Enviar feedback para o backend
    await fetch('/api/v1/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        feedback,
        rating,
        agent_name: agentName,
        message_id: messageId,
        timestamp: new Date().toISOString(),
      }),
    });
    
    setSubmitted(true);
    setTimeout(() => setSubmitted(false), 3000);
    setFeedback('');
    setRating(0);
  };
  
  if (submitted) {
    return (
      <div className="p-4 text-green-600 bg-green-50 rounded-lg">
        ✅ Obrigado pelo feedback! A IA vai aprender com isso.
      </div>
    );
  }
  
  return (
    <div className="p-4 border rounded-lg bg-white shadow-sm">
      <h3 className="font-semibold mb-2">📝 Feedback</h3>
      <p className="text-sm text-gray-600 mb-3">
        Ajude a IA a melhorar! Diga o que estava certo ou errado.
      </p>
      
      <div className="flex gap-1 mb-3">
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            onClick={() => setRating(star)}
            className={`text-2xl ${star <= rating ? 'text-yellow-500' : 'text-gray-300'}`}
          >
            ⭐
          </button>
        ))}
      </div>
      
      <Textarea
        placeholder="Ex: A resposta estava correta, mas podia ser mais detalhada..."
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
        className="mb-3"
      />
      
      <Button onClick={handleSubmit} disabled={!feedback.trim()}>
        Enviar Feedback
      </Button>
    </div>
  );
}
