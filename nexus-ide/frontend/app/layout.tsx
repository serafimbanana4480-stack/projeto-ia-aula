import type { Metadata, Viewport } from "next";
import "./globals.css";
import { MotionConfig } from "framer-motion";
import ThemeProvider from "./ThemeProvider";
import HydrateProvider from "./HydrateProvider";
import DataInitProvider from "./DataInitProvider";
import ErrorBoundary from "../components/ErrorBoundary";
import AuthGuard from "../components/auth/AuthGuard";
import InfrastructureProviders from "../components/InfrastructureProviders";

export const metadata: Metadata = {
  title: "NEXUS IDE - Inteligência Artificial Local",
  description: "NEXUS IDE - IDE assistida por IA com arquitetura multi-agente",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-PT" suppressHydrationWarning>
      <body className="h-screen overflow-hidden bg-nexus-bg text-nexus-text">
        <MotionConfig reducedMotion="user">
          <ErrorBoundary>
            <HydrateProvider>
              <AuthGuard>
                <ThemeProvider>
                  <DataInitProvider>
                    <InfrastructureProviders>{children}</InfrastructureProviders>
                  </DataInitProvider>
                </ThemeProvider>
              </AuthGuard>
            </HydrateProvider>
          </ErrorBoundary>
        </MotionConfig>
      </body>
    </html>
  );
}
