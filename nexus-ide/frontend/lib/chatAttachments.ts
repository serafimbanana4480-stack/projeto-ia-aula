export const MAX_CHAT_ATTACHMENTS = 5;
export const MAX_CHAT_ATTACHMENT_BYTES = 50_000;
export const MAX_CHAT_MESSAGE_CHARACTERS = 50_000;

const TEXT_FILE_EXTENSIONS = new Set([
  ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json",
  ".yaml", ".yml", ".toml", ".css", ".scss", ".html", ".xml", ".csv",
  ".sql", ".sh", ".bat", ".ps1", ".ini", ".cfg", ".gitignore",
  ".dockerfile", ".java", ".go", ".rs", ".php", ".rb", ".c", ".cpp",
  ".h", ".vue", ".svelte",
]);

const SENSITIVE_FILENAME = /(^|[._-])(env|secrets?|credentials?|private|token|password|id_rsa|id_ed25519)([._-]|$)/i;

export type ChatAttachmentRejection = "too_large" | "sensitive" | "unsupported";

export function getChatAttachmentRejection(file: Pick<File, "name" | "size" | "type">): ChatAttachmentRejection | null {
  if (SENSITIVE_FILENAME.test(file.name)) return "sensitive";
  if (file.size > MAX_CHAT_ATTACHMENT_BYTES) return "too_large";

  const extension = file.name.includes(".")
    ? `.${file.name.split(".").pop()!.toLowerCase()}`
    : "";
  if (file.type.startsWith("text/") || TEXT_FILE_EXTENSIONS.has(extension)) return null;
  return "unsupported";
}

export async function composeChatMessageWithAttachments(
  message: string,
  files: File[],
  stripTerminalCodes: (value: string) => string,
): Promise<string> {
  if (files.length > MAX_CHAT_ATTACHMENTS) {
    throw new Error(`Podes enviar até ${MAX_CHAT_ATTACHMENTS} ficheiros de texto por mensagem.`);
  }

  const parts = [message];
  for (const file of files) {
    const rejection = getChatAttachmentRejection(file);
    if (rejection === "sensitive") {
      throw new Error(`O ficheiro “${file.name}” parece conter credenciais e foi bloqueado.`);
    }
    if (rejection === "too_large") {
      throw new Error(`O ficheiro “${file.name}” excede o limite de 50 KB.`);
    }
    if (rejection === "unsupported") {
      throw new Error(`O ficheiro “${file.name}” não é texto. Imagens e binários ainda não são enviados ao modelo.`);
    }

    let content: string;
    try {
      content = stripTerminalCodes(await file.text());
    } catch {
      throw new Error(`Não foi possível ler o ficheiro “${file.name}”.`);
    }
    if (content.includes("\u0000")) {
      throw new Error(`O ficheiro “${file.name}” parece ser binário e foi bloqueado.`);
    }

    const safeContent = content.replace(/```/g, "\\`\\`\\`");
    parts.push(`\n\n[Conteúdo do ficheiro: ${file.name}]\n\`\`\`text\n${safeContent}\n\`\`\``);
    const composed = parts.join("");
    if (composed.length > MAX_CHAT_MESSAGE_CHARACTERS) {
      throw new Error("A mensagem com os ficheiros excede o limite de 50 mil caracteres. Remove ficheiros ou reduz o texto.");
    }
  }

  const composed = parts.join("");
  if (composed.length > MAX_CHAT_MESSAGE_CHARACTERS) {
    throw new Error("A mensagem excede o limite de 50 mil caracteres.");
  }
  return composed;
}
