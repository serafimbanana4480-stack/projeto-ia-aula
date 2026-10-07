"use client";
import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { User, Bot } from "lucide-react";
import ThinkingBlock from "@/components/chat/ThinkingBlock";
import ToolCallCard from "./ToolCallCard";
import CommandBar from "@/components/chat/CommandBar";

interface Message {
  id: string;
  role: "user" | "assistant" | "thinking" | "tool_call" | "tool_result";
  content: string;
  toolName?: string;
  args?: any;
  status?: "running" | "success" | "error";
  result?: any;
  error?: string;
  durationMs?: number;
  iteration?: number;
}

export default function ChatStream() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      role: "assistant",
      content: "Olá! Sou o NEXUS AI Assistant. Posso ajudar com código, análise de dados, web scraping e muito mais. Escolha um modo cognitivo acima para começar.",
    },
  ]);
  const [isStreaming, setIsStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async (message: string) => {
    const userMsg: Message = { id: Date.now().toString(), role: "user", content: message };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);

    // Simular streaming (em produção, conectar ao backend SSE)
    if (true) {
      const thinkingMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: "thinking",
        content: "Analyzing the request...",
        iteration: 1,
      };
      setMessages((prev) => [...prev, thinkingMsg]);

      if (true) {
        const assistantMsg: Message = {
          id: (Date.now() + 2).toString(),
          role: "assistant",
          content: "Entendi sua solicitação. Vou processar isso usando o modo Coder para gerar código de alta qualidade.",
        };
        setMessages((prev) => [...prev, assistantMsg]);
        setIsStreaming(false);
      }
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <AnimatePresence mode="popLayout">
          {messages.map((msg) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {msg.role === "user" ? (
                <div className="flex max-w-[80%] items-start gap-2">
                  <div className="rounded bg-nexus-accent px-4 py-2 text-sm text-black">
                    {msg.content}
                  </div>
                  <div className="flex h-8 w-8 items-center justify-center rounded bg-nexus-border">
                    <User className="h-4 w-4 text-gray-400" />
                  </div>
                </div>
              ) : msg.role === "thinking" ? (
                <ThinkingBlock content={msg.content} />
              ) : msg.role === "tool_call" ? (
                <ToolCallCard
                  toolName={msg.toolName!}
                  args={msg.args!}
                  status={msg.status!}
                  result={msg.result}
                  error={msg.error}
                  durationMs={msg.durationMs}
                />
              ) : (
                <div className="flex max-w-[80%] items-start gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded bg-nexus-border">
                    <Bot className="h-4 w-4 text-gray-400" />
                  </div>
                  <div className="rounded border border-nexus-border/50 bg-nexus-panel px-4 py-2 text-sm text-gray-300">
                    {msg.content}
                  </div>
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
        {isStreaming && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex items-center gap-2 text-xs text-gray-500"
          >
            <div className="h-2 w-2 animate-bounce rounded-full bg-nexus-accent" />
            <div className="h-2 w-2 animate-bounce rounded-full bg-nexus-accent" style={{ animationDelay: "0.1s" }} />
            <div className="h-2 w-2 animate-bounce rounded-full bg-nexus-accent" style={{ animationDelay: "0.2s" }} />
          </motion.div>
        )}
        <div ref={messagesEndRef} />
      </div>
      
      <CommandBar onSend={handleSend} disabled={isStreaming} />
    </div>
  );
}
