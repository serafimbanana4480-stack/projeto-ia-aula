export function stripAnsiCodes(text: string): string {
  return text.replace(/\u001b\[[0-9;]*[A-Za-z]/g, "");
}
