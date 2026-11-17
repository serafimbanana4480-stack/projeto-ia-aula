/**
 * Human-readable, recoverable descriptions for browser media failures.
 *
 * The UI never shows a raw ``DOMException`` name: each failure mode has a
 * concrete next action the user can take. The ``kind`` is also used to drive
 * the microphone diagnostic badge.
 */

export type MicrophoneErrorKind =
  | "denied"
  | "not-found"
  | "in-use"
  | "unsupported"
  | "insecure"
  | "unknown";

export interface MicrophoneError {
  kind: MicrophoneErrorKind;
  message: string;
}

export const MICROPHONE_ERROR_MESSAGES: Record<MicrophoneErrorKind, string> = {
  denied:
    "O acesso ao microfone foi recusado. Ativa a permissão nas definições do browser e tenta outra vez.",
  "not-found":
    "Não encontrei nenhum microfone. Liga um dispositivo e tenta outra vez.",
  "in-use":
    "O microfone está a ser usado por outra aplicação. Fecha-a e tenta outra vez.",
  unsupported:
    "Este browser não permite gravar áudio. Usa um browser compatível (Chrome, Edge, Firefox ou Safari) e uma ligação segura.",
  insecure:
    "O microfone só está disponível em HTTPS ou em localhost. Abre a página por um endereço seguro.",
  unknown:
    "Não consegui abrir o microfone. Verifica as permissões do browser e tenta outra vez.",
};

function nameOf(reason: unknown): string {
  if (reason && typeof reason === "object" && "name" in reason) {
    const name = (reason as { name?: unknown }).name;
    return typeof name === "string" ? name : "";
  }
  return "";
}

function messageOf(reason: unknown): string {
  if (reason instanceof Error && reason.message) return reason.message;
  return "";
}

export function describeMicrophoneError(reason: unknown): MicrophoneError {
  const name = nameOf(reason);

  if (name === "NotAllowedError" || name === "PermissionDeniedError" || name === "SecurityError") {
    return { kind: "denied", message: MICROPHONE_ERROR_MESSAGES.denied };
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError" || name === "OverconstrainedError") {
    return { kind: "not-found", message: MICROPHONE_ERROR_MESSAGES["not-found"] };
  }
  if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError") {
    return { kind: "in-use", message: MICROPHONE_ERROR_MESSAGES["in-use"] };
  }

  if (typeof navigator !== "undefined" && !navigator.mediaDevices) {
    if (typeof window !== "undefined" && window.isSecureContext === false) {
      return { kind: "insecure", message: MICROPHONE_ERROR_MESSAGES.insecure };
    }
    return { kind: "unsupported", message: MICROPHONE_ERROR_MESSAGES.unsupported };
  }

  if (name === "NotSupportedError" || name === "TypeError") {
    return { kind: "unsupported", message: MICROPHONE_ERROR_MESSAGES.unsupported };
  }

  const detail = messageOf(reason);
  if (detail) {
    return { kind: "unknown", message: `Não consegui abrir o microfone. ${detail}` };
  }
  return { kind: "unknown", message: MICROPHONE_ERROR_MESSAGES.unknown };
}

export function isAbortError(reason: unknown): boolean {
  return nameOf(reason) === "AbortError";
}