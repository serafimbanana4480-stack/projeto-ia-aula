/**
 * Explicit audio capture contract for NEXUS VOICE.
 *
 * The backend ``/api/voice/transcribe`` accepts a bounded set of container
 * types. The browser picks the first supported one so the request never relies
 * on an implicit default, and the size/duration limits mirror the server's
 * ``MAX_AUDIO_BYTES`` / 60 s decode limit. Recordings are held in memory only
 * for the duration of one turn and are never written to disk by the frontend.
 */

export const MAX_RECORDING_MS = 59_000;
export const MAX_AUDIO_BYTES = 10 * 1024 * 1024;

/** Ordered by preference: Opus in WebM is the smallest and most widely supported. */
export const PREFERRED_AUDIO_MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
  "audio/ogg",
  "audio/wav",
] as const;

export function supportsCapture(): boolean {
  if (typeof navigator === "undefined") return false;
  if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
    return false;
  }
  return typeof MediaRecorder !== "undefined";
}

export function pickAudioMimeType(): string | null {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return null;
  }
  return PREFERRED_AUDIO_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) ?? null;
}

/** Strip codec parameters so the value matches the backend's content-type check. */
export function baseMimeType(mime: string): string {
  return mime.split(";", 1)[0].trim().toLowerCase();
}

/** Stop every track and drop the ``ended`` handler so no stale callback fires. */
export function releaseStream(stream: MediaStream | null | undefined): void {
  if (!stream) return;
  for (const track of stream.getTracks()) {
    try {
      track.onended = null;
    } catch {
      /* Some implementations expose the handler as read-only. */
    }
    try {
      track.stop();
    } catch {
      /* A track may already be ended. */
    }
  }
}

export function formatElapsed(milliseconds: number): string {
  const safe = Number.isFinite(milliseconds) && milliseconds > 0 ? milliseconds : 0;
  const totalSeconds = Math.floor(safe / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}