"use client";
import { useState } from "react";
import { motion } from "framer-motion";
import { Send, Paperclip, Mic, Command } from "lucide-react";

interface CommandBarProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export default function CommandBar({ onSend, disabled = false }: CommandBarProps) {
  const [input, setInput] = useState("");

  const handleSend = () => {
    if (input.trim() && !disabled) {
      onSend(input);
      setInput("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <motion.div
      initial={{ y: 20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className="border-t border-nexus-border bg-nexus-panel/50 p-4 backdrop-blur-md"
    >
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1 rounded bg-nexus-border px-2 py-1">
          <Command className="h-3 w-3 text-gray-400" />
          <span className="text-xs text-gray-400">/</span>
        </div>
        
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything... (use /code, /plan, /analyze)"
          disabled={disabled}
          className="flex-1 bg-transparent text-sm text-gray-300 placeholder:text-gray-500 focus:outline-none"
        />
        
        <div className="flex items-center gap-2">
          <button className="rounded p-2 text-gray-400 hover:bg-nexus-border hover:text-gray-300">
            <Paperclip className="h-4 w-4" />
          </button>
          <button className="rounded p-2 text-gray-400 hover:bg-nexus-border hover:text-gray-300">
            <Mic className="h-4 w-4" />
          </button>
          <button
            onClick={handleSend}
            disabled={disabled || !input.trim()}
            className="rounded bg-nexus-accent p-2 text-black hover:bg-nexus-accent/80 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
      
      <div className="mt-2 flex gap-2 text-xs text-gray-500">
        <button className="rounded bg-nexus-border px-2 py-1 hover:bg-nexus-border/50">/code</button>
        <button className="rounded bg-nexus-border px-2 py-1 hover:bg-nexus-border/50">/plan</button>
        <button className="rounded bg-nexus-border px-2 py-1 hover:bg-nexus-border/50">/analyze</button>
        <button className="rounded bg-nexus-border px-2 py-1 hover:bg-nexus-border/50">/scrape</button>
      </div>
    </motion.div>
  );
}
