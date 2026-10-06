"use client";
import { create } from "zustand";
import { apiUrl } from "../lib/api";
import { authenticatedFetch } from "../lib/auth";

export interface AdvancedModeConfig {
  maximum_cycles?: number;
  maximum_parallel_agents?: number;
  require_all_tests?: boolean;
  minimum_quality_score?: number;
  allow_architecture_changes?: boolean;
  stop_on_critical_security_issue?: boolean;
  [key: string]: unknown;
}

export interface AdvancedModeGroup {
  label: string;
  description: string;
  icon: string;
  color: string;
  order: number;
}

export interface AdvancedMode {
  mode_id: string;
  display_name: string;
  description: string;
  group: string;
  icon: string;
  color: string;
  active: boolean;
  session_count: number;
  active_session_count?: number;
  total_session_count?: number;
  available: boolean;
  runtime_status?: "integrated" | "composed" | "unknown" | string;
  runtime_role?: string;
  runtime_summary?: string;
  handler?: string | null;
  config?: AdvancedModeConfig;
  execution_target?: { kind: string; agent: string | null };
  limitations?: string;
  activity_evidence_status?: string;
  evidence_count?: number;
  intervention_count?: number;
  checkpoint_count?: number;
  sessions?: Array<{
    session_id: string;
    state: string;
    start_time: string;
    updated_time: string;
    goal_count: number;
  }>;
}

export interface CommandAlias {
  aliases: string[];
  description: string;
  mode: string;
}

export interface AdvancedExecutionProfile {
  active_mode_ids: string[];
  applied_mode_ids: string[];
  policy_mode_ids: string[];
  primary_mode: string | null;
  preferred_agent: string | null;
  force_autonomous: boolean;
  summary: string;
  addon?: string;
}

export interface AdvancedModeHealth {
  healthy: boolean;
  active_modes: number;
  total_modes: number;
  modes: Record<string, {
    active: boolean;
    session_count: number;
    active_session_count?: number;
    total_session_count?: number;
    group: string;
    display_name: string;
    description: string;
    icon: string;
    color: string;
    runtime_status?: string;
    runtime_role?: string;
    runtime_summary?: string;
    handler?: string | null;
    available?: boolean;
    execution_target?: AdvancedMode["execution_target"];
    limitations?: string;
    activity_evidence_status?: string;
    evidence_count?: number;
    intervention_count?: number;
    checkpoint_count?: number;
  }>;
  groups: Record<string, AdvancedModeGroup>;
  execution_profile?: AdvancedExecutionProfile;
  activity_evidence_status?: string;
  disk_guard?: {
    status: string;
    write_blocked?: boolean;
    threshold_percent?: number;
    snapshot?: { free_percent: number; measured_at: string };
  };
}

interface AdvancedModeStore {
  modes: Record<string, AdvancedMode>;
  groups: Record<string, AdvancedModeGroup>;
  commands: Record<string, CommandAlias>;
  commandsLoading: boolean;
  commandsError: string | null;
  activeModeIds: string[];
  loading: boolean;
  error: string | null;
  health: AdvancedModeHealth | null;
  executionProfile: AdvancedExecutionProfile | null;
  pendingModeIds: string[];
  actionError: string | null;
  lastSyncedAt: number | null;

  loadModes: () => Promise<void>;
  loadCommands: () => Promise<void>;
  activateMode: (modeId: string) => Promise<{ success: boolean; message?: string; session_id?: string }>;
  deactivateMode: (modeId: string) => Promise<{ success: boolean; message?: string }>;
  getModeStatus: (modeId: string) => Promise<AdvancedMode | null>;
  refreshHealth: () => Promise<void>;
  resolveCommand: (command: string) => Promise<{ resolved_to: string; display_name: string; description: string; icon: string; color: string } | null>;
  isModeActive: (modeId: string) => boolean;
  getActiveModesByGroup: (group: string) => AdvancedMode[];
}

let healthRequest: Promise<void> | null = null;
let healthGeneration = 0;

async function responseError(response: Response): Promise<string> {
  let detail: unknown;
  try {
    const data = await response.json();
    detail = data.detail ?? data.message ?? data.error;
  } catch { /* A gateway may return HTML instead of JSON. */ }
  if (response.status === 401) return "Sessão expirada. Volta a iniciar sessão.";
  return typeof detail === "string" ? detail : `O servidor recusou a alteração (HTTP ${response.status}).`;
}

export const useAdvancedModeStore = create<AdvancedModeStore>((set, get) => ({
  modes: {},
  groups: {},
  commands: {},
  commandsLoading: false,
  commandsError: null,
  activeModeIds: [],
  loading: false,
  error: null,
  health: null,
  executionProfile: null,
  pendingModeIds: [],
  actionError: null,
  lastSyncedAt: null,

  loadModes: async () => {
    if (healthRequest) return healthRequest;
    const generation = healthGeneration;
    set({ loading: true });
    healthRequest = (async () => {
    try {
      const res = await authenticatedFetch(apiUrl("/api/advanced-modes/health"), {
        credentials: "include",
        signal: AbortSignal.timeout(10_000),
      });
      if (!res.ok) throw new Error(await responseError(res));
        const data: AdvancedModeHealth = await res.json();
        if (!data.modes || typeof data.modes !== "object" || Array.isArray(data.modes)) {
          throw new Error("O backend devolveu um catálogo inválido.");
        }
        // A response started before a confirmed mutation cannot restore the
        // old state. The mutation will request a fresh snapshot afterwards.
        if (generation !== healthGeneration) return;
        const activeIds = Object.entries(data.modes)
          .filter(([, m]) => m.active)
          .map(([id]) => id);
        set({
          health: data,
          executionProfile: data.execution_profile ?? null,
          modes: Object.fromEntries(
            Object.entries(data.modes).map(([id, m]) => [
              id,
              {
                mode_id: id,
                display_name: m.display_name,
                description: m.description ?? "",
                group: m.group,
                icon: m.icon,
                color: m.color,
                 active: m.active,
                 session_count: m.session_count,
                 active_session_count: m.active_session_count ?? m.session_count,
                 total_session_count: m.total_session_count ?? m.session_count,
                 available: m.available ?? true,
                 runtime_status: m.runtime_status,
                 runtime_role: m.runtime_role,
                 runtime_summary: m.runtime_summary,
                 handler: m.handler,
                 execution_target: m.execution_target,
                 limitations: m.limitations,
                 activity_evidence_status: m.activity_evidence_status,
                 evidence_count: m.evidence_count,
                 intervention_count: m.intervention_count,
                 checkpoint_count: m.checkpoint_count,
               } as AdvancedMode,
            ])
          ),
          groups: data.groups || {},
          activeModeIds: activeIds,
          lastSyncedAt: Date.now(),
          error: null,
        });
    } catch (e) {
      if (generation === healthGeneration) {
        set({ error: e instanceof Error ? e.message : "Sem ligação ao backend." });
      }
    } finally {
      set({ loading: false });
      healthRequest = null;
    }
    })();
    return healthRequest;
  },

  loadCommands: async () => {
    set({ commandsLoading: true, commandsError: null });
    try {
      const res = await authenticatedFetch(apiUrl("/api/advanced-modes/commands"), {
        credentials: "include",
      });
      if (!res.ok) {
        set({
          commandsError: `Não foi possível carregar os comandos (HTTP ${res.status})`,
          commandsLoading: false,
        });
        return;
      }
      const data = await res.json();
      const rawCommands =
        data && typeof data === "object" && data.commands && typeof data.commands === "object"
          ? data.commands as Record<string, Partial<CommandAlias>>
          : {};
      const commands = Object.fromEntries(
        Object.entries(rawCommands).flatMap(([modeId, command]) => {
          const aliases = Array.isArray(command.aliases)
            ? command.aliases.filter((alias): alias is string => typeof alias === "string")
            : [];
          if (aliases.length === 0) return [];
          return [[modeId, {
            aliases,
            description: typeof command.description === "string" ? command.description : "",
            mode: typeof command.mode === "string" ? command.mode : modeId,
          } satisfies CommandAlias]];
        }),
      );
      set({
        commands,
        commandsError:
          Object.keys(commands).length === 0 ? "O backend não devolveu comandos disponíveis" : null,
        commandsLoading: false,
      });
    } catch (error) {
      set({
        commandsError:
          error instanceof Error
            ? `Não foi possível carregar os comandos: ${error.message}`
            : "Não foi possível carregar os comandos",
        commandsLoading: false,
      });
    }
  },

  activateMode: async (modeId: string) => {
    if (get().pendingModeIds.includes(modeId)) return { success: false, message: "A alteração já está em curso." };
    healthGeneration += 1;
    set((state) => ({ pendingModeIds: [...state.pendingModeIds, modeId], actionError: null }));
    try {
      const res = await authenticatedFetch(apiUrl(`/api/advanced-modes/${modeId}/activate`), {
        method: "POST",
        credentials: "include",
        signal: AbortSignal.timeout(10_000),
      });
      if (!res.ok) throw new Error(await responseError(res));
      const data = await res.json();
      if (data.success !== true) throw new Error(data.message ?? data.error ?? "O servidor não confirmou a ativação.");
      healthGeneration += 1;
        set((state) => ({
          activeModeIds: state.activeModeIds.includes(modeId)
            ? state.activeModeIds
            : [...state.activeModeIds, modeId],
          modes: {
            ...state.modes,
            // Activation is idempotent on the backend and reuses an existing
            // session. Do not invent a new session count before the next
            // server refresh confirms one exists.
            [modeId]: { ...state.modes[modeId], active: true },
          },
          executionProfile: null,
        }));
      await get().refreshHealth();
      return data;
    } catch (e) {
      const message = e instanceof Error ? e.message : "A ativação falhou.";
      set({ actionError: message });
      return { success: false, message };
    } finally {
      set((state) => ({ pendingModeIds: state.pendingModeIds.filter((id) => id !== modeId) }));
    }
  },

  deactivateMode: async (modeId: string) => {
    if (get().pendingModeIds.includes(modeId)) return { success: false, message: "A alteração já está em curso." };
    healthGeneration += 1;
    set((state) => ({ pendingModeIds: [...state.pendingModeIds, modeId], actionError: null }));
    try {
      const res = await authenticatedFetch(apiUrl(`/api/advanced-modes/${modeId}/deactivate`), {
        method: "POST",
        credentials: "include",
        signal: AbortSignal.timeout(10_000),
      });
      if (!res.ok) throw new Error(await responseError(res));
      const data = await res.json();
      if (data.success !== true) throw new Error(data.message ?? data.error ?? "O servidor não confirmou a desativação.");
      healthGeneration += 1;
        set((state) => ({
          activeModeIds: state.activeModeIds.filter((id) => id !== modeId),
          modes: { ...state.modes, [modeId]: { ...state.modes[modeId], active: false } },
          executionProfile: null,
        }));
      await get().refreshHealth();
      return data;
    } catch (e) {
      const message = e instanceof Error ? e.message : "A desativação falhou.";
      set({ actionError: message });
      return { success: false, message };
    } finally {
      set((state) => ({ pendingModeIds: state.pendingModeIds.filter((id) => id !== modeId) }));
    }
  },

  getModeStatus: async (modeId: string) => {
    try {
      const res = await authenticatedFetch(apiUrl(`/api/advanced-modes/${modeId}`), {
        credentials: "include",
        signal: AbortSignal.timeout(10_000),
      });
      if (res.ok) {
        return await res.json();
      }
      return null;
    } catch {
      return null;
    }
  },

  refreshHealth: async () => {
    if (healthRequest) await healthRequest;
    await get().loadModes();
  },

  resolveCommand: async (command: string) => {
    try {
      const res = await authenticatedFetch(apiUrl(`/api/commands/resolve?command=${encodeURIComponent(command)}`), {
        credentials: "include",
      });
      if (res.ok) {
        return await res.json();
      }
      return null;
    } catch {
      return null;
    }
  },

  isModeActive: (modeId: string) => get().activeModeIds.includes(modeId),

  getActiveModesByGroup: (group: string) =>
    Object.values(get().modes).filter((m) => m.group === group && m.available && m.active),
}));
