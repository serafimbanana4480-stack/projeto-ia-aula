/**
 * Stable, client-side identifiers for the voice session, each conversational
 * turn and each speech playback.
 *
 * They are used only for idempotency and diagnostics on the frontend: a
 * late transcription or a late synthesis fragment can be matched back to the
 * exact turn/audio that produced it and discarded when superseded. They are
 * never sent to a remote provider and never persisted.
 */

function randomToken(): string {
  const cryptoApi = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }
  const time = Date.now().toString(36);
  const noise = Math.random().toString(36).slice(2, 10);
  return `${time}-${noise}`;
}

export function newVoiceSessionId(): string {
  return `voice-${randomToken()}`;
}

export function newTurnId(): string {
  return `turn-${randomToken()}`;
}

export function newAudioId(): string {
  return `audio-${randomToken()}`;
}