export interface ChatComposerState {
  busyOtherSession: boolean;
  streaming: boolean;
  sessionId: string;
  input: string;
  planCreating: boolean;
}

export function getChatComposerPlaceholder({
  busyOtherSession,
  streaming,
}: Pick<ChatComposerState, "busyOtherSession" | "streaming">): string {
  if (busyOtherSession) return "Outra conversa está a gerar…";
  if (streaming) return "Envia uma orientação ao NEXUS…";
  return "Escreve o que queres fazer…  (/ comandos · @ contexto)";
}

export function isChatComposerSendDisabled({
  input,
  sessionId,
  busyOtherSession,
  planCreating,
}: ChatComposerState): boolean {
  return (
    !input.trim() ||
    !sessionId ||
    sessionId === "default" ||
    sessionId.startsWith("local-") ||
    busyOtherSession ||
    planCreating
  );
}
