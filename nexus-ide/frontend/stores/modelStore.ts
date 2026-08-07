import { create } from "zustand";
import { getModelCatalog, type ProviderCatalogStatus } from "../lib/api";

export interface Model {
  id: string;
  name?: string;
  tier: string;
  pricing?: string;
  estimated_tokens_per_sec?: number;
  size_gb: number;
  provider?: string;
  parameter_size?: string;
  contextWindow?: number;
  description?: string;
  status: "available" | "loading" | "error";
  free?: boolean;
  color?: string;
  inputPricePer1M?: number | null;
  outputPricePer1M?: number | null;
  capabilities?: string[];
}

interface ModelStore {
  /**
   * The model id sent to `/api/chat`. Empty string means auto-route.
   *
   * This is now a concrete provider model id (e.g. `anthropic/claude-sonnet-4`)
   * and the backend honours it verbatim. It used to be downgraded to a router
   * tier before sending, which silently ran a different model.
   */
  activeModel: string;
  /** Provider selected alongside the concrete model id. */
  activeProvider: string;
  models: Model[];
  /** Per-provider status, so the UI can explain an empty list. */
  providerStatus: ProviderCatalogStatus[];
  modelsLoaded: boolean;
  modelsLoading: boolean;
  modelsError: string | null;
  setActiveModel: (model: string, provider?: string) => void;
  setModels: (models: Model[]) => void;
  /** Load the catalog. Pass `refresh` to bypass the 10-minute server cache. */
  loadModels: (refresh?: boolean) => Promise<void>;
}

/** Empty string = let the smart router pick. */
const AUTO_MODEL = "";

export const useModelStore = create<ModelStore>((set, get) => ({
  // Default to auto-routing instead of pinning a hardcoded id that may not
  // exist for the user's configured providers.
  activeModel: AUTO_MODEL,
  activeProvider: "",
  models: [],
  providerStatus: [],
  modelsLoaded: false,
  modelsLoading: false,
  modelsError: null,

  setActiveModel: (model, provider = "") => set({ activeModel: model, activeProvider: provider }),
  setModels: (models) => set({ models, modelsLoaded: true }),

  loadModels: async (refresh = false) => {
    // Guard against concurrent loads only. A `modelsLoaded` check used to
    // short-circuit here too, which made refresh impossible: models unlocked
    // by a newly added API key never appeared without a full page reload.
    if (get().modelsLoading || (!refresh && get().modelsLoaded)) return;
    set({ modelsLoading: true, modelsError: null });
    try {
      const catalog = await getModelCatalog(refresh);
      const mapped: Model[] = (catalog.models ?? []).map((m) => ({
        id: m.id,
        name: m.name || m.id,
        tier: m.tier,
        pricing: m.pricing,
        estimated_tokens_per_sec: m.estimated_tokens_per_sec,
        contextWindow: m.context_window ?? 0,
        size_gb: 0,
        provider: m.provider,
        description: m.description,
        status: "available" as const,
        free: m.free ?? false,
        color: m.color ?? "#64748b",
        inputPricePer1M: m.input_price_per_1m ?? null,
        outputPricePer1M: m.output_price_per_1m ?? null,
        capabilities: m.capabilities ?? [],
      }));

      // When the list is empty, explain why rather than rendering nothing.
      const failures = (catalog.providers ?? []).filter(
        (p) => p.error && p.configured,
      );

      set({
        models: mapped,
        providerStatus: catalog.providers ?? [],
        modelsLoaded: true,
        modelsLoading: false,
        modelsError:
          mapped.length === 0 && failures.length > 0
            ? failures.map((p) => `${p.label}: ${p.error}`).join(" · ")
            : null,
      });
    } catch (error) {
      // Report the failure. The old implementation set only `modelsLoading:
      // false`, so a broken endpoint looked identical to "you have no models".
      set({
        modelsLoading: false,
        modelsLoaded: true,
        modelsError:
          error instanceof Error ? error.message : "Falha a carregar modelos",
      });
    }
  },
}));
