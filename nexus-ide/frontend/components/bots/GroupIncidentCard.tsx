"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, ChevronDown, Settings2 } from "lucide-react";
import { affectedAgents, type GroupIncident } from "../../lib/groupIncidents";

export default function GroupIncidentCard({
  incident,
  busy,
  onRetry,
  onChooseModel,
}: {
  incident: GroupIncident;
  busy: boolean;
  onRetry: (content: string) => void;
  onChooseModel: (botIds: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const agents = affectedAgents(incident);
  const count = incident.messages.length;
  const explanation = incident.messages[0]?.content ?? "";
  const botIds = incident.messages.map((message) => message.bot_id).filter((id): id is string => Boolean(id));
  const uniqueBotIds = [...new Set(botIds)];
  const canRetry = Boolean(incident.turnUser?.content.trim()) && !busy;

  return (
    <article
      className="rounded-2xl border border-[color:var(--nx-rose)]/35 bg-[color:color-mix(in_srgb,var(--nx-rose)_8%,var(--nx-surface-1))] p-4"
      data-testid="group-incident"
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-rose-400/15 text-rose-200">
          <AlertTriangle size={16} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-rose-100">Falha de provider nesta volta</h3>
            <span className="rounded-full border border-rose-300/30 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-rose-100">
              {count} {count === 1 ? "ocorrência" : "ocorrências"}
            </span>
            <span className="text-[11px] text-rose-100/80">Estado: falhou</span>
          </div>
          <p className="mt-2 text-sm leading-6 text-zinc-100">{explanation}</p>
          <p className="mt-2 text-xs leading-5 text-zinc-400">
            Agentes afetados: {agents.join(", ")}. As mensagens técnicas ficam neste incidente.
            Nenhuma repetição foi iniciada automaticamente.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link
              href="/settings"
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 px-2.5 py-1.5 text-xs font-medium text-zinc-100 hover:bg-white/5"
            >
              <Settings2 size={13} aria-hidden="true" />
              Ver configuração
            </Link>
            <button
              type="button"
              onClick={() => onChooseModel(uniqueBotIds)}
              className="rounded-lg border border-white/15 px-2.5 py-1.5 text-xs font-medium text-zinc-100 hover:bg-white/5"
            >
              Escolher outro modelo
            </button>
            <button
              type="button"
              disabled={!canRetry}
              onClick={() => {
                if (incident.turnUser) onRetry(incident.turnUser.content);
              }}
              className="rounded-lg border border-white/15 px-2.5 py-1.5 text-xs font-medium text-zinc-100 hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
              title={busy ? "Há uma volta em curso" : "Envia de novo a mensagem desta volta. Não é automático."}
            >
              Repetir mensagem
            </button>
            <button
              type="button"
              aria-expanded={open}
              onClick={() => setOpen((value) => !value)}
              className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium text-violet-200 hover:bg-white/5"
            >
              Detalhes técnicos
              <ChevronDown size={14} className={`transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
            </button>
          </div>
          {open && (
            <ol className="mt-3 space-y-2 border-t border-white/10 pt-3">
              {incident.messages.map((message, index) => (
                <li key={message.id} className="rounded-lg bg-black/20 px-3 py-2 text-xs leading-5 text-zinc-300">
                  <p className="font-medium text-zinc-100">
                    {index + 1}. {message.bot_name || "Agente sem nome"} · {message.id}
                  </p>
                  <p className="text-zinc-500">{message.created_at || "Hora desconhecida"}</p>
                  <p className="mt-1 whitespace-pre-wrap break-words">{message.content}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </article>
  );
}
