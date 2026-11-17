/** Pure layout for the room composer. Kept separate so height rules are testable. */

export const COMPOSER_FIELD_MIN = 44;
export const COMPOSER_MAX_RATIO = 0.4;

export function composerFieldHeight(
  scrollHeight: number,
  viewportHeight: number,
  chrome = 0,
): { height: number; overflow: boolean } {
  const viewport = Number.isFinite(viewportHeight) && viewportHeight > 0 ? viewportHeight : 800;
  const extra = Number.isFinite(chrome) && chrome > 0 ? chrome : 0;
  const cap = Math.max(COMPOSER_FIELD_MIN, Math.round(viewport * COMPOSER_MAX_RATIO) - extra);
  const content = Math.max(COMPOSER_FIELD_MIN, Math.ceil(Number.isFinite(scrollHeight) ? scrollHeight : 0));
  const height = Math.min(content, cap);
  return { height, overflow: content > height + 1 };
}

export function slashTokenAtCaret(value: string, caret: number): boolean {
  return /(?:^|\s)\/[^\s]*$/.test(value.slice(0, Math.max(0, caret)));
}
