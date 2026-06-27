import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="pt">
      <body style={{ 
        margin: 0, 
        padding: 0, 
        backgroundColor: '#0b0b14', 
        color: 'white',
        fontFamily: 'system-ui, sans-serif'
      }}>
        {children}
      </body>
    </html>
  );
}
