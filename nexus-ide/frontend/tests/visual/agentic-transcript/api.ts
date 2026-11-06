// The isolated visual fixture never grants approvals.
export async function confirmTool(): Promise<never> {
  throw new Error("Aprovações não estão disponíveis no teste visual.");
}
