"use client";

import { AuthProvider } from "../lib/auth-context";
import { QueryProvider } from "../components/QueryProvider";

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryProvider>
      <AuthProvider>{children}</AuthProvider>
    </QueryProvider>
  );
}
