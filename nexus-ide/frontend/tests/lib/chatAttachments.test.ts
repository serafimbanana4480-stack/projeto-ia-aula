import { describe, expect, it, vi } from "vitest";
import {
  composeChatMessageWithAttachments,
  getChatAttachmentRejection,
  MAX_CHAT_ATTACHMENT_BYTES,
  MAX_CHAT_MESSAGE_CHARACTERS,
} from "../../lib/chatAttachments";

function file(name: string, content: string, type = "text/plain"): File {
  return {
    name,
    size: new TextEncoder().encode(content).length,
    type,
    text: async () => content,
  } as File;
}

describe("chat attachment contract", () => {
  it("accepts small text files and includes their actual contents", async () => {
    const result = await composeChatMessageWithAttachments(
      "Revê este ficheiro",
      [file("notes.txt", "linha 1\nlinha 2")],
      (value) => value,
    );

    expect(result).toContain("[Conteúdo do ficheiro: notes.txt]");
    expect(result).toContain("linha 1\nlinha 2");
  });

  it("rejects image, binary, oversized, and secret-looking files before send", async () => {
    expect(getChatAttachmentRejection(file("photo.png", "x", "image/png"))).toBe("unsupported");
    expect(getChatAttachmentRejection(file("payload.bin", "x", "application/octet-stream"))).toBe("unsupported");
    expect(getChatAttachmentRejection(file(".env", "TOKEN=x"))).toBe("sensitive");
    expect(
      getChatAttachmentRejection(
        file("large.txt", "x".repeat(MAX_CHAT_ATTACHMENT_BYTES + 1)),
      ),
    ).toBe("too_large");

    await expect(
      composeChatMessageWithAttachments("", [file("photo.png", "x", "image/png")], (value) => value),
    ).rejects.toThrow(/Imagens e binários ainda não são enviados/);
    await expect(
      composeChatMessageWithAttachments("", [file(".env", "TOKEN=x")], (value) => value),
    ).rejects.toThrow(/credenciais/);
  });

  it("does not allow attachment content to exceed the API message limit", async () => {
    const oversizedMessage = "x".repeat(MAX_CHAT_MESSAGE_CHARACTERS - 10);
    await expect(
      composeChatMessageWithAttachments(
        oversizedMessage,
        [file("notes.txt", "content")],
        (value) => value,
      ),
    ).rejects.toThrow(/50 mil caracteres/);
  });

  it("stops safely when a selected file cannot be read", async () => {
    const unreadable = file("notes.txt", "ignored");
    vi.spyOn(unreadable, "text").mockRejectedValue(new Error("read denied"));
    await expect(
      composeChatMessageWithAttachments("", [unreadable], (value) => value),
    ).rejects.toThrow(/Não foi possível ler/);
  });
});
