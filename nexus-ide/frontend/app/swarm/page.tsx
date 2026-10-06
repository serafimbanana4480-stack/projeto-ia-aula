"use client";
import { Suspense, useState, useCallback, useEffect } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import AppShell from "../../components/layout/AppShell";
import SwarmPanel from "../../components/swarm/SwarmPanel";
import ThinkingBlock from "../../components/chat/ThinkingBlock";
import { useChatInput } from "../../hooks/useChatInput";

function SwarmClient() {
  const [insertText, setInsertText] = useState<string>("");
  const { setValue: setChatDraft } = useChatInput();
  // The reasoning text has to come from somewhere. The SWARM panel publishes
  // its per-agent reasoning on the same window event it already uses for the
  // answer; without a setter the block could only ever render null.
  const [thinking, setThinking] = useState<string>("");
  const insertIntoChat = useCallback((text: string) => {
    setInsertText(text);
    setChatDraft(text);
  }, [setChatDraft]);

  // Listen for cross-component events from the SWARM panel
  useEffect(() => {
    if (typeof window === "undefined") return;
    const handler = (e: Event) => {
      const ce = e as CustomEvent<string>;
      setInsertText(ce.detail);
    };
    window.addEventListener("nexus:chat-input", handler as EventListener);
    const thinkingHandler = (e: Event) => {
      const ce = e as CustomEvent<string | undefined>;
      setThinking(typeof ce.detail === "string" ? ce.detail : "");
    };
    window.addEventListener("nexus:swarm-thinking", thinkingHandler as EventListener);
    return () => {
      window.removeEventListener("nexus:chat-input", handler as EventListener);
      window.removeEventListener("nexus:swarm-thinking", thinkingHandler as EventListener);
    };
  }, []);

  return (
    // A plain <div>, not <main> — AppShell already provides the page's
    // <main> landmark, so this stays a nested content block instead of a
    // second landmark.
    <div className="flex h-full flex-col">
      <div className="grid h-full grid-cols-1 lg:grid-cols-[1fr_400px]">
        <div className="border-r border-nexus-border">
          <SwarmPanel sessionId="default" onInsertIntoChat={insertIntoChat} />
        </div>
        <aside className="bg-nexus-bg/30 p-4">
          <div className="rounded-xl border border-fuchsia-500/20 bg-gradient-to-br from-fuchsia-500/5 to-violet-500/5 p-4">
            <h3 className="mb-2 text-sm font-semibold text-nexus-text">Enviar para o chat</h3>
            <p className="mb-3 text-[11px] text-nexus-muted">
              Quando lanças uma execução SWARM, a resposta final é inserida aqui automaticamente para poderes refinar ou continuar.
            </p>
            <ThinkingBlock content={thinking} defaultOpen />
            <div className="min-h-32 whitespace-pre-wrap rounded-lg border border-nexus-border bg-nexus-bg/40 p-3 text-[11px] leading-relaxed text-nexus-text">
              {insertText || "_(nada enviado ainda — lança uma execução para ver a resposta aqui)_"}
            </div>
            <Link
              href="/"
              aria-disabled={!insertText}
              tabIndex={insertText ? 0 : -1}
              onClick={(event) => {
                if (!insertText) event.preventDefault();
              }}
              className={`mt-3 inline-flex min-h-9 items-center gap-2 rounded-lg px-3 text-xs font-semibold transition-colors ${
                insertText
                  ? "bg-fuchsia-500/15 text-fuchsia-200 hover:bg-fuchsia-500/25"
                  : "pointer-events-none bg-nexus-card/40 text-nexus-faint"
              }`}
            >
              Abrir no chat
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          </div>
          <div className="mt-4 rounded-xl border border-nexus-border bg-nexus-card/30 p-4 text-[11px] leading-relaxed text-nexus-muted">
            <h4 className="mb-1.5 text-xs font-semibold text-nexus-text">Como funciona o SWARM</h4>
            <ol className="list-decimal space-y-1 pl-4">
              <li>O <strong>Coordenador</strong> escolhe o modo operacional a partir do teu objetivo.</li>
              <li>Recupera evidência do código indexado através de RAG.</li>
              <li>Pesquisa externa é recolhida se o modo a exigir.</li>
              <li>Os agentes certos colaboram através do barramento de mensagens.</li>
              <li>O <strong>Revisor</strong> pontua o resultado em 4 eixos.</li>
              <li>Só as propostas que passam no controlo de qualidade são aprovadas.</li>
            </ol>
          </div>
        </aside>
      </div>
    </div>
  );
}

export default function SwarmPage() {
  return (
    <AppShell title="SWARM" noPadding>
      <Suspense fallback={<div className="flex h-full items-center justify-center text-nexus-muted">A carregar SWARM...</div>}>
        <SwarmClient />
      </Suspense>
    </AppShell>
  );
}
