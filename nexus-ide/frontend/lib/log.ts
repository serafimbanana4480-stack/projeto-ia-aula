/**
 * Safe logging helper that only emits to console in development.
 * Prevents console noise in production builds.
 */
const isDev = process.env.NODE_ENV === "development";

export const log = {
  error: (...args: unknown[]): void => {
    if (isDev) console.error(...args);
  },
  warn: (...args: unknown[]): void => {
    if (isDev) console.warn(...args);
  },
  info: (...args: unknown[]): void => {
    if (isDev) console.info(...args);
  },
  debug: (...args: unknown[]): void => {
    if (isDev) console.debug(...args);
  },
};
