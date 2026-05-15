import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Kraken Alpha Agent — Hackathon Submission",
  description:
    "Production-grade trading agent for the lablab AI Agent Olympics — Kraken Trading Performance track. 232/232 tests, 30-day xStocks backtest on real Kraken OHLC data, fully audited.",
  metadataBase: new URL("https://kraken-alpha-agent.vercel.app"),
  openGraph: {
    title: "Kraken Alpha Agent — Hackathon Submission",
    description:
      "232/232 tests passed. 30-day xStocks backtest on real Kraken OHLC data. PEDSL-CY venue restriction transparently documented.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full bg-[var(--background)] text-[var(--text-primary)]">
        {children}
      </body>
    </html>
  );
}
