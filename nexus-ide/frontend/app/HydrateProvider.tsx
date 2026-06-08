"use client";

import { useHydrateStores } from "../hooks/useHydrateStores";

export default function HydrateProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  useHydrateStores();
  return <>{children}</>;
}
