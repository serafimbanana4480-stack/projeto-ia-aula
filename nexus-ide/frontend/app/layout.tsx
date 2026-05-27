import type { Metadata } from "next";
import "./globals.css";
import ThemeProvider from "./ThemeProvider";
import ErrorBoundary from "../components/ErrorBoundary";

export const metadata: Metadata = {
  title: "LUSO AI - Inteligência que constrói futuro",
  description: "NEXUS IDE powered by LUSO AI",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="h-screen overflow-hidden bg-nexus-bg text-nexus-text">
        <ErrorBoundary>
          <ThemeProvider>{children}</ThemeProvider>
        </ErrorBoundary>
      </body>
    </html>
  );
}
