export function studioDayKey(timestamp: string | number | Date | undefined): string {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

export function studioDayLabel(timestamp: string | number | Date | undefined): string {
  if (!timestamp) return "";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const sameDay = studioDayKey(date) === studioDayKey(now);
  if (sameDay) return "Hoje";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (studioDayKey(date) === studioDayKey(yesterday)) return "Ontem";
  return date.toLocaleDateString("pt-PT", { day: "numeric", month: "short" });
}
