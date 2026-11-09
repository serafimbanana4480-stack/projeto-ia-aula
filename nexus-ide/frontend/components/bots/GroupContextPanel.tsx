"use client";

import { X } from "lucide-react";
import type { Bot } from "../../lib/bots";
import { BotAvatar, BotStatusPill } from "./botsUi";
import GroupRuns from "./GroupRuns";

type Group = { id: string; name: string; bot_ids: string[]; last_message: string | null };

function availability(bot: Bot | undefined): { label: string; tone: "neutral" | "warn" | "danger" } {
  if (!bot) return { label: "Bot indisponível", tone: "danger" };
  if (!bot.provider || !bot.model) return { label: "Configuração em falta", tone: "warn" };
  return { label: "Configurado · inferência não verificada", tone: "neutral" };
}

export default function GroupContextPanel({
  group,
  bots,
  objective,
  executionLabel,
  onClose,
}: {
  group: Group;
  bots: Bot[];
  objective: string;
  executionLabel: string;
  onClose: () => void;
}) {
  const participants = group.bot_ids.map((id) => bots.find((bot) => bot.id === id) ?? null);

  return (
    <aside
      aria-label="Contexto do grupo"
      className="flex h-full min-h-0 w-full flex-col border-l border-white/10 bg-[#14151b]"
    >
      <div className="flex items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">Contexto</h2>
          <p className="text-[11px] text-zinc-500">Dados reais do grupo e das execuções</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Fechar contexto" className="rounded-lg p-2 text-zinc-400 hover:bg-white/5 hover:text-white">
          <X size={16} />
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        <section>
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Objetivo</h3>
          <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-zinc-200">{objective}</p>
        </section>
        <section>
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Execução</h3>
          <p className="mt-1 text-sm text-zinc-200">{executionLabel}</p>
        </section>
        <section>
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Participantes</h3>
          <ul className="mt-2 space-y-2">
            {participants.map((bot, index) => {
              const id = group.bot_ids[index];
              const state = availability(bot ?? undefined);
              const name = bot?.name || "Bot indisponível";
              return (
                <li key={id} className="rounded-xl border border-white/10 p-3">
                  <div className="flex items-center gap-2">
                    <BotAvatar name={name} id={id} compact />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{name}</p>
                      <p className="truncate text-[11px] text-zinc-500">{bot?.description?.trim() || "Função não descrita"}</p>
                    </div>
                  </div>
                  <p className="mt-2 break-all text-[11px] text-zinc-400">
                    {bot?.provider || "Provedor não configurado"} · {bot?.model || "Modelo não configurado"}
                  </p>
                  <div className="mt-2">
                    <BotStatusPill tone={state.tone}>{state.label}</BotStatusPill>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
        <section>
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Plano e ferramentas</h3>
          <p className="mt-1 text-xs leading-5 text-zinc-500">
            Esta conversa de grupo não expõe plano, ficheiros alterados nem tool calls.
            As execuções com leitura de ficheiro, quando existirem, aparecem abaixo.
          </p>
        </section>
        <GroupRuns groupId={group.id} embedded />
      </div>
    </aside>
  );
}
