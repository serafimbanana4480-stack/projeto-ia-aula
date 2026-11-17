/** Shared response reader for the voice endpoints. */

export async function responseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail.trim()) return body.detail;
  } catch {
    /* Fall back to the status code below. */
  }
  return `Erro ${response.status}`;
}