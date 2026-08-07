import { create } from "zustand";
import {
  getProviderCatalog,
  getProviderModels,
  refreshProviderCatalog,
  validateProviderKey,
  type AvailableModel,
  type KeyValidationResult,
  type ProviderSpec,
} from "../lib/api";

/** Result of the last "Test key" click for one provider. */
export interface KeyTestState {
  status: "idle" | "testing" | "valid" | "invalid";
  result: KeyValidationResult | null;
  testedAt: number;
}

interface ProviderModelsState {
  models: AvailableModel[];
  loading: boolean;
  /** Why the list is empty — missing key, rate limit, unreachable host. */
  error: string | null;
  cached: boolean;
  fetchedAt: number;
}

interface ProviderStore {
  providers: ProviderSpec[];
  loading: boolean;
  error: string | null;
  loaded: boolean;
  keyTests: Record<string, KeyTestState>;
  modelsByProvider: Record<string, ProviderModelsState>;

  loadProviders: () => Promise<void>;
  /** Test a key without saving. Pass the typed value, or omit to re-test the stored one. */
  testKey: (providerId: string, apiKey?: string) => Promise<KeyValidationResult>;
  loadProviderModels: (providerId: string, refresh?: boolean) => Promise<void>;
  /** Invalidate the server cache and reload — call after saving a key. */
  invalidate: (providerId?: string) => Promise<void>;
  clearKeyTest: (providerId: string) => void;
}

const EMPTY_MODELS: ProviderModelsState = {
  models: [],
  loading: false,
  error: null,
  cached: false,
  fetchedAt: 0,
};

function messageOf(error: unknown): string {
  if (error instanceof Error) return error.message;
  return typeof error === "string" ? error : "Erro desconhecido";
}

export const useProviderStore = create<ProviderStore>((set, get) => ({
  providers: [],
  loading: false,
  error: null,
  loaded: false,
  keyTests: {},
  modelsByProvider: {},

  loadProviders: async () => {
    if (get().loading) return;
    set({ loading: true, error: null });
    try {
      const providers = await getProviderCatalog();
      set({ providers, loading: false, loaded: true, error: null });
    } catch (error) {
      // Surface the failure. The previous model store swallowed errors, so a
      // down backend looked identical to "you have no models".
      set({ loading: false, loaded: true, error: messageOf(error) });
    }
  },

  testKey: async (providerId, apiKey) => {
    set((state) => ({
      keyTests: {
        ...state.keyTests,
        [providerId]: { status: "testing", result: null, testedAt: 0 },
      },
    }));
    try {
      const result = await validateProviderKey(providerId, apiKey);
      set((state) => ({
        keyTests: {
          ...state.keyTests,
          [providerId]: {
            status: result.valid ? "valid" : "invalid",
            result,
            testedAt: Date.now(),
          },
        },
      }));
      return result;
    } catch (error) {
      const result: KeyValidationResult = {
        provider: providerId,
        valid: false,
        error: messageOf(error),
        models_count: 0,
      };
      set((state) => ({
        keyTests: {
          ...state.keyTests,
          [providerId]: { status: "invalid", result, testedAt: Date.now() },
        },
      }));
      return result;
    }
  },

  loadProviderModels: async (providerId, refresh = false) => {
    const current = get().modelsByProvider[providerId];
    if (current?.loading) return;
    set((state) => ({
      modelsByProvider: {
        ...state.modelsByProvider,
        [providerId]: { ...(current ?? EMPTY_MODELS), loading: true, error: null },
      },
    }));
    try {
      const data = await getProviderModels(providerId, refresh);
      set((state) => ({
        modelsByProvider: {
          ...state.modelsByProvider,
          [providerId]: {
            models: data.models ?? [],
            loading: false,
            error: data.error ?? null,
            cached: Boolean(data.cached),
            fetchedAt: data.fetched_at ?? 0,
          },
        },
      }));
    } catch (error) {
      set((state) => ({
        modelsByProvider: {
          ...state.modelsByProvider,
          [providerId]: {
            ...(current ?? EMPTY_MODELS),
            loading: false,
            error: messageOf(error),
          },
        },
      }));
    }
  },

  invalidate: async (providerId) => {
    try {
      await refreshProviderCatalog(providerId);
    } catch {
      // A failed cache bust is not worth blocking the UI; the reload below
      // still hits the server and the TTL expires on its own.
    }
    await get().loadProviders();
    if (providerId) await get().loadProviderModels(providerId, true);
  },

  clearKeyTest: (providerId) =>
    set((state) => {
      const { [providerId]: _removed, ...rest } = state.keyTests;
      return { keyTests: rest };
    }),
}));
