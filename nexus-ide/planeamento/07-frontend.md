# NEXUS IDE — Frontend Detalhado

## 1. Visão Geral do Frontend

O frontend NEXUS IDE é uma aplicação Next.js 15 que fornece uma interface de utilizador completa para desenvolvimento assistido por IA. O frontend é desenhado para parecer um IDE nativo (similar a VS Code), com Monaco Editor, terminal integrado, e painel de chat com streaming SSE.

### 1.1 Stack Tecnológico

| Componente | Tecnologia | Versão | Justificativa |
|-------------|-----------|--------|---------------|
| Framework | Next.js | 15.0.0 | App Router, Server Components, Streaming |
| Linguagem | TypeScript | 5.6.3 | Type safety, IntelliSense, Refactoring seguro |
| Editor | Monaco Editor | 4.6.0 | Usado por VS Code (familiaridade), API rica |
| Terminal | xterm.js | 5.3.0 | Padrão da indústria, Canvas-based |
| Styling | Tailwind CSS | 3.4.14 | Utility-first, Design system consistente |
| State | Zustand | 5.0.0 | Leve, simples, sem providers |
| Icons | Lucide React | 0.454.0 | Consistente, tree-shakeable |
| Charts | Recharts | 2.13.0 | Declarativo, React-friendly |
| D3 | d3 | 7.9.0 | Visualizações complexas (quando necessário) |

### 1.2 Estrutura de Diretórios

```
frontend/
├── app/                      # Next.js App Router
│   ├── page.tsx             # Home page (IDE layout)
│   ├── layout.tsx           # Root layout
│   ├── dashboard/           # Dashboard route
│   │   └── page.tsx
│   └── api/                 # API routes (proxy)
│       └── chat/
│           └── route.ts     # Proxy para backend
├── components/              # React components
│   ├── chat/                # Chat panel
│   │   ├── ChatPanel.tsx
│   │   ├── MessageList.tsx
│   │   └── InputArea.tsx
│   ├── editor/              # Editor components
│   │   ├── MonacoEditor.tsx
│   │   ├── FileExplorer.tsx
│   │   ├── TabBar.tsx
│   │   └── StatusBar.tsx
│   ├── terminal/            # Terminal
│   │   └── Terminal.tsx
│   ├── dashboard/           # Dashboard
│   │   ├── MetricsChart.tsx
│   │   ├── AgentStatus.tsx
│   │   └── AlertPanel.tsx
│   └── ui/                  # UI components (shadcn/ui)
│       ├── Button.tsx
│       ├── Input.tsx
│       └── ...
├── hooks/                   # Custom React hooks
│   ├── useChat.ts           # Chat logic
│   ├── useSSE.ts            # SSE connection
│   ├── useFiles.ts          # File operations
│   └── useTerminal.ts      # Terminal logic
├── lib/                     # Utilities
│   ├── utils.ts             # Helper functions
│   ├── api.ts               # API client
│   └── constants.ts         # Constants
└── tests/                   # Vitest tests
    ├── setup.ts             # Test setup
    ├── vitest.config.ts      # Vitest config
    └── ...
```

## 2. Next.js App Router

### 2.1 Por que App Router?

**Alternativas:**
- **Pages Router:** Next.js 12 e anteriores (legado)
- **React Router:** Framework separado
- **Remix:** Full-stack framework

**Por que App Router?**
- **Server Components:** Renderização no servidor (performance)
- **Streaming:** Suporte nativo para streaming (SSE)
- **Nested Layouts:** Layouts aninhados (flexibilidade)
- **Route Groups:** Organização de rotas
- **Futuro:** App Router é o futuro do Next.js

### 2.2 Layout Principal

```typescript
// app/layout.tsx
import "./globals.css";
import { Inter } from "next/font/google";
import { Providers } from "./providers";

const inter = Inter({ subsets: ["latin"] });

export const metadata = {
  title: "NEXUS IDE",
  description: "AI-powered development environment",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
```

**Por que Providers Wrapper?**
- **Context providers:** Zustand, theme, etc.
- **Isolamento:** Providers separados do layout
- **Testabilidade:** Fácil de mock providers

### 2.3 Página Principal (IDE Layout)

```typescript
// app/page.tsx
"use client";

import { MonacoEditor } from "@/components/editor/MonacoEditor";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { Terminal } from "@/components/terminal/Terminal";
import { FileExplorer } from "@/components/editor/FileExplorer";

export default function HomePage() {
  return (
    <div className="h-screen flex flex-col bg-[#1e1e1e] text-white">
      {/* Top Bar */}
      <div className="h-8 bg-[#323233] flex items-center px-4">
        <span className="font-semibold">NEXUS IDE</span>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex">
        {/* Left Sidebar - File Explorer */}
        <div className="w-64 bg-[#252526] border-r border-[#3c3c3c]">
          <FileExplorer />
        </div>

        {/* Center - Monaco Editor */}
        <div className="flex-1 flex flex-col">
          <MonacoEditor />
        </div>

        {/* Right Sidebar - Chat Panel */}
        <div className="w-96 bg-[#252526] border-l border-[#3c3c3c]">
          <ChatPanel />
        </div>
      </div>

      {/* Bottom - Terminal */}
      <div className="h-48 bg-[#1e1e1e] border-t border-[#3c3c3c]">
        <Terminal />
      </div>
    </div>
  );
}
```

**Por que este Layout?**
- **Familiaridade:** Similar a VS Code (curva de aprendizagem reduzida)
- **Eficiência:** Espaço otimizado para código
- **Flexibilidade:** Painéis podem ser redimensionados/colapsados

## 3. Monaco Editor Integration

### 3.1 Por que Monaco Editor?

**Alternativas:**
- **CodeMirror:** Menos familiar, menos recursos
- **Ace Editor:** Menos mantido, API menos rica
- **VS Code Web:** Muito pesado, dependência complexa

**Por que Monaco Editor?**
- **Usado por VS Code:** Familiar para a maioria dos programadores
- **Suporte para 100+ linguagens:** Cobertura completa
- **API rica:** Extensível, customizável
- **Ativamente mantido:** Pela Microsoft
- **Performance:** Canvas-based rendering

### 3.2 Configuração Básica

```typescript
// components/editor/MonacoEditor.tsx
"use client";

import Editor, { OnMount } from "@monaco-editor/react";
import * as monaco from "monaco-editor";

export function MonacoEditor() {
  const handleEditorDidMount: OnMount = (editor, monaco) => {
    // Register AI inline suggest provider
    registerInlineSuggestProvider(editor, monaco);
    
    // Register completion provider
    registerCompletionProvider(editor, monaco);
    
    // Set theme
    monaco.editor.setTheme("vs-dark");
  };

  return (
    <Editor
      height="100%"
      defaultLanguage="python"
      defaultValue="# Start coding..."
      theme="vs-dark"
      options={{
        minimap: { enabled: true },
        fontSize: 14,
        lineNumbers: "on",
        scrollBeyondLastLine: false,
        automaticLayout: true,
        tabSize: 4,
        wordWrap: "on",
        renderWhitespace: "selection",
        inlineSuggest: {
          enabled: true,
        },
      }}
      onMount={handleEditorDidMount}
    />
  );
}
```

### 3.3 AI Inline Suggest

**Implementação:**

```typescript
function registerInlineSuggestProvider(
  editor: monaco.editor.IStandaloneCodeEditor,
  monaco: any
) {
  const provider: monaco.languages.InlineCompletionItemProvider = {
    async provideInlineCompletionItems(model, position) {
      const beforeCursor = model.getValueInRange({
        startLineNumber: 1,
        startColumn: 1,
        endLineNumber: position.lineNumber,
        endColumn: position.column,
      });

      // Call backend API for suggestions
      try {
        const response = await fetch("/api/suggest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: beforeCursor }),
        });

        const suggestions = await response.json();

        return {
          items: suggestions.map((s: any) => ({
            text: s.completion,
            range: new monaco.Range(
              position.lineNumber,
              position.column,
              position.lineNumber,
              position.column,
            ),
            command: {
              id: "accept-suggestion",
              title: "Accept suggestion",
            },
          })),
        };
      } catch (error) {
        console.error("Failed to get suggestions:", error);
        return { items: [] };
      }
    },
  };

  monaco.languages.registerInlineCompletionItemProvider("python", provider);
}
```

**Por que Inline Suggest?**
- **Menos contexto switching:** Não precisa de abrir chat
- **Mais rápido:** Sugestão imediata
- **Familiar:** Similar a GitHub Copilot
- **Complementa chat:** Chat para tasks complexas, inline para sugestões rápidas

### 3.4 Completion Provider

**Implementação:**

```typescript
function registerCompletionProvider(
  editor: monaco.editor.IStandaloneCodeEditor,
  monaco: any
) {
  const provider: monaco.languages.CompletionItemProvider = {
    async provideCompletionItems(model, position) {
      const lineContent = model.getLineContent(position.lineNumber);
      const lineUntilCursor = lineContent.substring(0, position.column - 1);

      // Check if triggering character
      if (!lineUntilCursor.endsWith(".")) {
        return { suggestions: [] };
      }

      // Call backend for completions
      try {
        const response = await fetch("/api/completions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: lineUntilCursor }),
        });

        const completions = await response.json();

        return {
          suggestions: completions.map((c: any) => ({
            label: c.label,
            kind: monaco.languages.CompletionItemKind.Function,
            insertText: c.insertText,
            detail: c.detail,
            documentation: c.documentation,
          })),
        };
      } catch (error) {
        console.error("Failed to get completions:", error);
        return { suggestions: [] };
      }
    },
  };

  monaco.languages.registerCompletionItemProvider("python", provider);
}
```

### 3.5 Diagnostics (AI)

**Implementação:**

```typescript
function registerDiagnosticsProvider(
  editor: monaco.editor.IStandaloneCodeEditor,
  monaco: any
) {
  const diagnostics = monaco.languages.createDiagnosticCollection("nexus-ai");

  // Periodically ask backend for diagnostics
  setInterval(async () => {
    const model = editor.getModel();
    if (!model) return;

    const code = model.getValue();

    try {
      const response = await fetch("/api/diagnostics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });

      const diagnosticResults = await response.json();

      const markers = diagnosticResults.map((d: any) => ({
        severity: monaco.MarkerSeverity.Error,
        message: d.message,
        startLineNumber: d.line,
        startColumn: d.column,
        endLineNumber: d.line,
        endColumn: d.column + d.length,
      }));

      diagnostics.set(model.uri, markers);
    } catch (error) {
      console.error("Failed to get diagnostics:", error);
    }
  }, 5000); // Every 5 seconds
}
```

**Por que Diagnostics AI?**
- **Pró-ativo:** Deteta bugs antes de executar
- **Contextual:** Entende código, não apenas sintaxe
- **Educacional:** Explica por que é um erro

## 4. Chat Panel

### 4.1 Responsabilidade

O Chat Panel é a interface principal de comunicação com os agentes NEXUS IDE. Exibe mensagens do utilizador e dos agentes, permite streaming de respostas, e mostra o estado atual do agente.

### 4.2 Implementação

```typescript
// components/chat/ChatPanel.tsx
"use client";

import { useState } from "react";
import { useSSE } from "@/hooks/useSSE";
import { InputArea } from "./InputArea";
import { MessageList } from "./MessageList";

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentAgent, setCurrentAgent] = useState<string | null>(null);

  const { data, isConnected } = useSSE("/api/chat/stream");

  // Handle SSE data
  useEffect(() => {
    if (data) {
      const event = JSON.parse(data);

      switch (event.type) {
        case "routing":
          setCurrentAgent(event.agent);
          break;
        case "thinking":
          setMessages((prev) => [
            ...prev,
            { role: "assistant", content: event.content, type: "thinking" },
          ]);
          break;
        case "chunk":
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === "assistant" && last.type === "content") {
              return [
                ...prev.slice(0, -1),
                { ...last, content: last.content + event.content },
              ];
            }
            return [
              ...prev,
              { role: "assistant", content: event.content, type: "content" },
            ];
          });
          break;
        case "done":
          setIsStreaming(false);
          break;
      }
    }
  }, [data]);

  const handleSendMessage = async (content: string) => {
    setMessages((prev) => [
      ...prev,
      { role: "user", content },
    ]);
    setIsStreaming(true);

    // Send to backend
    await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: generateSessionId(),
        query: content,
        context: {},
      }),
    });
  };

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4">
        <MessageList messages={messages} />
      </div>

      {/* Input */}
      <div className="border-t border-[#3c3c3c] p-4">
        <InputArea
          disabled={isStreaming}
          onSend={handleSendMessage}
        />
      </div>

      {/* Status */}
      {currentAgent && (
        <div className="bg-[#323233] px-4 py-2 text-sm">
          Active: {currentAgent}
        </div>
      )}
    </div>
  );
}
```

### 4.3 Por que SSE (Server-Sent Events)?

**Alternativas:**
- **WebSocket:** Bidirecional (overkill para chat)
- **Polling:** Ineficiente (muitos requests)
- **gRPC:** Complexo, não browser nativo

**Por que SSE?**
- **Unidirectional:** Server → client (suficiente para chat)
- **HTTP padrão:** Menos firewall issues
- **Reconnection automática:** EventSource nativo
- **Streaming:** Suporte nativo para streaming

### 4.4 Hook useSSE

```typescript
// hooks/useSSE.ts
import { useState, useEffect } from "react";

export function useSSE(endpoint: string) {
  const [data, setData] = useState<string>("");
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const eventSource = new EventSource(endpoint);

    eventSource.onopen = () => setIsConnected(true);
    eventSource.onerror = () => setIsConnected(false);

    eventSource.onmessage = (event) => {
      setData(event.data);
    };

    return () => eventSource.close();
  }, [endpoint]);

  return { data, isConnected };
}
```

**Por que Hook Personalizado?**
- **Reutilização:** Pode usar SSE em múltiplos componentes
- **Abstração:** Esconde complexidade do EventSource
- **Estado:** Gerencia estado de conexão

## 5. Terminal

### 5.1 Responsabilidade

O Terminal é uma interface de linha de comando integrada que permite executar comandos, ver output, e interagir com o sistema.

### 5.2 Implementação

```typescript
// components/terminal/Terminal.tsx
"use client";

import { useEffect, useRef } from "react";
import { Terminal } from "xterm";
import { FitAddon } from "xterm-addon-fit";

export function Terminal() {
  const terminalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const terminal = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      theme: {
        background: "#1e1e1e",
        foreground: "#d4d4d4",
      },
    });

    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);

    if (terminalRef.current) {
      terminal.open(terminalRef.current);
      fitAddon.fit();
    }

    // Handle resize
    const handleResize = () => fitAddon.fit();
    window.addEventListener("resize", handleResize);

    // Handle input
    terminal.onData((data) => {
      // Send to backend
      fetch("/api/terminal/input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input: data }),
      });
    });

    // Receive output from backend
    const eventSource = new EventSource("/api/terminal/output");
    eventSource.onmessage = (event) => {
      terminal.write(event.data);
    };

    return () => {
      window.removeEventListener("resize", handleResize);
      eventSource.close();
      terminal.dispose();
    };
  }, []);

  return <div ref={terminalRef} className="h-full" />;
}
```

### 5.3 Por que xterm.js?

**Alternativas:**
- **jQuery Terminal:** Descontinuado
- **TTY.js:** Menos recursos
- **WebTTY:** Menos mantido

**Por que xterm.js?**
- **Padrão da indústria:** VS Code usa xterm.js
- **Performance:** Canvas-based rendering
- **Plugins:** fit, web-links, etc.
- **Ativamente mantido:** Continua sendo desenvolvido

### 5.4 Por que WebSocket para Terminal?

```typescript
// Terminal usa WebSocket (não SSE)
const ws = new WebSocket("ws://localhost:8000/terminal");

ws.onmessage = (event) => {
  terminal.write(event.data);
};

ws.onopen = () => {
  terminal.write("Connected to terminal\r\n");
};
```

**Por que WebSocket e não SSE?**
- **Bidirecional:** Terminal precisa enviar input E receber output
- **Baixa latência:** WebSocket é mais rápido que polling
- **Real-time:** Necessário para interatividade

## 6. File Explorer

### 6.1 Responsabilidade

O File Explorer mostra a estrutura de diretórios do projeto, permite navegar, abrir ficheiros, e gerir tabs.

### 6.2 Implementação

```typescript
// components/editor/FileExplorer.tsx
"use client";

import { useState } from "react";
import { ChevronRight, ChevronDown, File, Folder } from "lucide-react";

interface FileNode {
  name: string;
  type: "file" | "directory";
  children?: FileNode[];
}

export function FileExplorer() {
  const [nodes, setNodes] = useState<FileNode[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    // Fetch file tree from backend
    fetch("/api/files/tree")
      .then((res) => res.json())
      .then((data) => setNodes(data));
  }, []);

  const toggleExpand = (path: string) => {
    const newExpanded = new Set(expanded);
    if (newExpanded.has(path)) {
      newExpanded.delete(path);
    } else {
      newExpanded.add(path);
    }
    setExpanded(newExpanded);
  };

  const openFile = (path: string) => {
    // Open file in Monaco Editor
    fetch("/api/files/read", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    })
      .then((res) => res.json())
      .then((data) => {
        // Send to Monaco Editor via event bus
        window.dispatchEvent(
          new CustomEvent("openFile", { detail: { path, content: data.content } })
        );
      });
  };

  return (
    <div className="p-2">
      {nodes.map((node) => (
        <FileTreeNode
          key={node.name}
          node={node}
          path={node.name}
          expanded={expanded}
          onToggle={toggleExpand}
          onOpen={openFile}
        />
      ))}
    </div>
  );
}

function FileTreeNode({
  node,
  path,
  expanded,
  onToggle,
  onOpen,
}: {
  node: FileNode;
  path: string;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  onOpen: (path: string) => void;
}) {
  const isExpanded = expanded.has(path);
  const isDirectory = node.type === "directory";

  return (
    <div>
      <div
        className="flex items-center gap-2 px-2 py-1 hover:bg-[#2a2d2e] cursor-pointer"
        onClick={() => {
          if (isDirectory) {
            onToggle(path);
          } else {
            onOpen(path);
          }
        }}
      >
        {isDirectory ? (
          isExpanded ? (
            <ChevronDown size={14} />
          ) : (
            <ChevronRight size={14} />
          )
        ) : (
          <File size={14} />
        )}
        <span className="text-sm">{node.name}</span>
      </div>
      {isDirectory && isExpanded && node.children && (
        <div className="pl-4">
          {node.children.map((child) => (
            <FileTreeNode
              key={child.name}
              node={child}
              path={`${path}/${child.name}`}
              expanded={expanded}
              onToggle={onToggle}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

### 6.3 Por que Árvore Recursiva?

- **Flexível:** Suporta profundidade arbitrária
- **Eficiente:** Renderiza apenas nós expandidos
- **Familiar:** Similar a VS Code

## 7. State Management (Zustand)

### 7.1 Store Global

```typescript
// lib/store.ts
import { create } from "zustand";

interface AppState {
  // Chat state
  chat: {
    messages: Message[];
    isStreaming: boolean;
    currentAgent: string | null;
  };

  // Editor state
  editor: {
    openFiles: File[];
    activeFile: File | null;
    unsavedChanges: Set<string>;
  };

  // Actions
  addMessage: (message: Message) => void;
  openFile: (file: File) => void;
  closeFile: (path: string) => void;
  setActiveFile: (file: File) => void;
  markUnsaved: (path: string) => void;
  markSaved: (path: string) => void;
}

export const useStore = create<AppState>((set) => ({
  chat: {
    messages: [],
    isStreaming: false,
    currentAgent: null,
  },

  editor: {
    openFiles: [],
    activeFile: null,
    unsavedChanges: new Set(),
  },

  addMessage: (message) =>
    set((state) => ({
      chat: {
        ...state.chat,
        messages: [...state.chat.messages, message],
      },
    })),

  openFile: (file) =>
    set((state) => ({
      editor: {
        ...state.editor,
        openFiles: [...state.editor.openFiles, file],
        activeFile: file,
      },
    })),

  closeFile: (path) =>
    set((state) => ({
      editor: {
        ...state.editor,
        openFiles: state.editor.openFiles.filter((f) => f.path !== path),
        activeFile:
          state.editor.activeFile?.path === path
            ? null
            : state.editor.activeFile,
      },
    })),

  setActiveFile: (file) =>
    set((state) => ({
      editor: {
        ...state.editor,
        activeFile: file,
      },
    })),

  markUnsaved: (path) =>
    set((state) => ({
      editor: {
        ...state.editor,
        unsavedChanges: new Set([...state.editor.unsavedChanges, path]),
      },
    })),

  markSaved: (path) =>
    set((state) => {
      const unsaved = new Set(state.editor.unsavedChanges);
      unsaved.delete(path);
      return {
        editor: {
          ...state.editor,
          unsavedChanges: unsaved,
        },
      };
    }),
}));
```

### 7.2 Por que Zustand?

**Alternativas:**
- **Redux:** Overkill, muito boilerplate
- **Context API:** Re-render desnecessário, performance
- **Recoil:** Mais complexo, menos maduro
- **Jotai:** Atômico, mas menos familiar

**Por que Zustand?**
- **Leve:** 1kb minified
- **Simples:** API minimalista
- **Sem providers:** Boilerplate zero
- **TypeScript-friendly:** Types automáticos
- **DevTools:** Integrados
- **Persistência:** Middleware opcional

## 8. Dashboard

### 8.1 Responsabilidade

O Dashboard mostra métricas do sistema em tempo real, status dos agentes, e alertas. É alimentado pelo DASHBOARD AGENT via SSE.

### 8.2 Implementação

```typescript
// app/dashboard/page.tsx
"use client";

import { useSSE } from "@/hooks/useSSE";
import { MetricsChart } from "@/components/dashboard/MetricsChart";
import { AgentStatus } from "@/components/dashboard/AgentStatus";
import { AlertPanel } from "@/components/dashboard/AlertPanel";

export default function DashboardPage() {
  const { data, isConnected } = useSSE("/api/dashboard/stream");

  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);

  useEffect(() => {
    if (data) {
      const event = JSON.parse(data);

      switch (event.type) {
        case "metric":
          setMetrics((prev) => ({
            ...prev,
            [event.name]: event.value,
          }));
          break;
        case "alert":
          setAlerts((prev) => [...prev, event]);
          break;
      }
    }
  }, [data]);

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">NEXUS IDE Dashboard</h1>

      {/* Metrics */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <MetricsChart metrics={metrics} />
      </div>

      {/* Agent Status */}
      <div className="mb-6">
        <AgentStatus />
      </div>

      {/* Alerts */}
      <div>
        <AlertPanel alerts={alerts} />
      </div>
    </div>
  );
}
```

### 8.3 Métricas Exibidas

| Métrica | Descrição | Visualização |
|---------|-----------|---------------|
| Requests/s | Taxa de requests por segundo | Line chart |
| Latency p95 | Latência 95th percentile | Line chart |
| Error Rate | Taxa de erros (4xx, 5xx) | Line chart |
| Agent Pool Utilization | % de agentes ativos | Bar chart |
| Tokens/s | Tokens gerados por segundo | Line chart |
| Queue Depth | Profundidade da fila por modelo | Bar chart |

### 8.4 Por que Recharts?

**Alternativas:**
- **Chart.js:** Menos React-friendly
- **D3:** Muito verboso (baixo nível)
- **Victory:** Menos mantido

**Por que Recharts?**
- **Declarativo:** JSX-friendly
- **React-native:** React-first
- **Composable:** Componentes modulares
- **Types:** TypeScript automático
- **Performance:** SVG-based, rápido

## 9. API Proxy

### 9.1 Responsabilidade

O API proxy no frontend roteia requests para o backend, adicionando headers, auth, e tratando erros.

### 9.2 Implementação

```typescript
// app/api/chat/route.ts
import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // Proxy to backend
    const response = await fetch("http://localhost:8000/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    const data = await response.text();

    // Return SSE stream
    return new NextResponse(data, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
      },
    });
  } catch (error) {
    return NextResponse.json({ error: "Failed to proxy request" }, { status: 500 });
  }
}
```

### 9.3 Por que Proxy?

- **CORS:** Evita problemas de CORS
- **Security:** Esconde URL do backend
- **Auth:** Pode adicionar headers de auth centralizados
- **Caching:** Pode implementar caching no edge (Vercel)

## 10. Styling (Tailwind CSS)

### 10.1 Por que Tailwind CSS?

**Alternativas:**
- **CSS Modules:** Mais verboso, não reutilizável
- **Styled Components:** Runtime overhead
- **Emotion:** Similar ao Styled Components
- **CSS-in-JS:** Runtime overhead

**Por que Tailwind CSS?**
- **Utility-first:** Classes reutilizáveis
- **Zero runtime:** CSS gerado em build time
- **Design system:** Consistência garantida
- **Customização:** Fácil de estender
- **Performance:** Purge automático de CSS não usado

### 10.2 Tema Dark

```css
/* app/globals.css */
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --bg-primary: #1e1e1e;
  --bg-secondary: #252526;
  --bg-tertiary: #323233;
  --border-color: #3c3c3c;
  --text-primary: #d4d4d4;
  --text-secondary: #858585;
  --accent: #007acc;
}

body {
  background-color: var(--bg-primary);
  color: var(--text-primary);
}
```

**Por que Tema Dark?**
- **Padrão IDE:** VS Code, IntelliJ, etc. são dark
- **Reduz fadiga:** Menos brilho para os olhos
- **Profissional:** Aparência mais séria

## 11. Performance

### 11.1 Otimizações

**Server Components:**
- Renderização no servidor (menos JS no cliente)
- Streaming de HTML (faster First Contentful Paint)
- Reduz bundle size

**Code Splitting:**
- Lazy loading de componentes pesados (Monaco, xterm)
- Dynamic imports para rotas

**Caching:**
- SWR para dados (stale-while-revalidate)
- Cache de API responses

**Bundle Analysis:**
- Analisar bundle com webpack-bundle-analyzer
- Remover dependências não usadas

### 11.2 Lazy Loading

```typescript
// Lazy loading Monaco Editor
const MonacoEditor = dynamic(
  () => import("@/components/editor/MonacoEditor"),
  {
    loading: () => <div>Loading editor...</div>,
    ssr: false, // Monaco não funciona no server
  }
);

// Lazy loading Terminal
const Terminal = dynamic(
  () => import("@/components/terminal/Terminal"),
  {
    loading: () => <div>Loading terminal...</div>,
    ssr: false, // xterm não funciona no server
  }
);
```

## 12. Conclusão

O frontend NEXUS IDE é desenhado para ser:
- **Familiar:** Similar a VS Code (curva de aprendizagem reduzida)
- **Performante:** Server Components, lazy loading, caching
- **Responsivo:** Streaming SSE, WebSocket real-time
- **Extensível:** Plugins para Monaco, hooks customizados
- **Type-safe:** TypeScript em todo o código

A escolha de tecnologias é baseada em maturidade, ecossistema, e alinhamento com os princípios do projeto (privacidade, performance, usabilidade).
