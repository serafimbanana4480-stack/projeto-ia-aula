import type { Metadata } from "next";
import "./globals.css";
import ThemeProvider from "./ThemeProvider";
import ErrorBoundary from "../components/ErrorBoundary";

export const metadata: Metadata = {
  title: "NEXUS IDE - Inteligência Artificial Local",
  description: "NEXUS IDE - IDE assistida por IA com arquitetura multi-agente",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt" suppressHydrationWarning>
      <body className="h-screen overflow-hidden bg-nexus-bg text-nexus-text">
        <ErrorBoundary>
          <ThemeProvider>{children}</ThemeProvider>
        </ErrorBoundary>
      </body>
    </html>
  );
}
