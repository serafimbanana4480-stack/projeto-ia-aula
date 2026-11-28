import { Archive, ArrowLeft, ArrowRight, Bot as BotIcon, Cpu, Plus, Users } from "lucide-react";
import type { Bot } from "../../lib/bots";
import { BotAvatar } from "./botsUi";

export default function WorkspaceOverview({
  bots, loading, failed, groupDisabled, onCreate, onGroups, onChoose, onBack,
}: {
  bots: Bot[];
  loading: boolean;
  failed: boolean;
  groupDisabled: boolean;
  onCreate: () => void;
  onGroups: () => void;
  onChoose: (bot: Bot) => void;
  onBack: () => void;
}) {
  const active = bots.filter((bot) => !bot.archived);
  const configured = active.filter((bot) => bot.provider && bot.model).length;
  const stats = [
    { label: "Bots ativos", value: active.length, icon: BotIcon },
    { label: "Modelos configurados", value: configured, icon: Cpu },
    { label: "Arquivados", value: bots.length - active.length, icon: Archive },
  ];
  const recent = active.filter((bot) => bot.last_message).sort((a, b) => b.last_active_at.localeCompare(a.last_active_at)).slice(0, 4);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-7 sm:px-8 lg:px-10">
      <div className="mx-auto grid max-w-5xl gap-6">
        <button type="button" onClick={onBack} className="nx-bot-action ml-9 w-fit md:hidden"><ArrowLeft size={15} /> Voltar às conversas</button>
        <header className="nx-bot-hero relative isolate overflow-hidden rounded-3xl border p-6 sm:p-9">
          <div aria-hidden="true" className="nx-bot-pattern" />
          <span className="nx-bot-mark inline-grid size-11 place-items-center rounded-xl border"><BotIcon size={23} /></span>
          <h2 className="mt-5 max-w-xl text-3xl font-semibold tracking-tight sm:text-[2.65rem] sm:leading-tight">Espaço de bots</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-[var(--nx-text-dim)]">
            Configura assistentes para o teu trabalho, retoma conversas e reúne modelos diferentes no mesmo grupo.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <button type="button" className="nx-bot-action nx-bot-primary" onClick={onCreate}><Plus size={17} /> Criar bot</button>
            <button type="button" className="nx-bot-action" disabled={groupDisabled} onClick={onGroups}><Users size={17} /> Abrir grupos</button>
          </div>
        </header>
        <dl className="grid grid-cols-3 gap-2 sm:gap-3">
          {stats.map(({ label, value, icon: Icon }) => (
            <div key={label} className="nx-bot-card min-w-0 rounded-2xl border p-3 sm:p-4">
              <dt className="flex items-center gap-2 text-xs font-medium leading-5 text-[var(--nx-text-dim)]">
                <Icon size={15} aria-hidden="true" className="hidden shrink-0 text-[var(--nx-accent-bright)] sm:block" /> {label}
              </dt>
              <dd className="mt-1 text-2xl font-semibold tabular-nums">{loading || failed ? "—" : value}</dd>
            </div>
          ))}
        </dl>
        {!loading && !failed && recent.length > 0 && (
          <section aria-labelledby="recent-bots">
            <h3 id="recent-bots" className="mb-3 text-base font-semibold">Bots recentes</h3>
            <div className="grid gap-2 sm:grid-cols-2 sm:gap-3">
              {recent.map((bot) => (
                <button key={bot.id} type="button" className="nx-bot-card nx-bot-item flex min-w-0 items-center gap-3 rounded-2xl border p-3 text-left" onClick={() => onChoose(bot)}>
                  <BotAvatar name={bot.name} id={bot.id} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{bot.name}</span>
                    <span className="mt-1 block truncate text-xs text-[var(--nx-text-dim)]">{bot.model || "Modelo por configurar"}</span>
                  </span>
                  <ArrowRight size={16} className="shrink-0 text-[var(--nx-text-faint)]" />
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
