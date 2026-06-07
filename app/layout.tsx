import type { Metadata } from "next";
import { DM_Mono, Fraunces, Inter } from "next/font/google";
import { CopilotKit } from "@copilotkit/react-core";
import "@copilotkit/react-ui/styles.css";
import "./globals.css";

// Editorial display face — warm, optical, confident headlines (the Coachella-leaning
// centerpiece type). Body face — clean, quiet, highly legible. Mono is retained
// purely for tabular data readouts (BPM, scores, ids) that read as instrument data.
const display = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
  display: "swap",
});

const body = Inter({
  variable: "--font-body",
  subsets: ["latin"],
  display: "swap",
});

const dmMono = DM_Mono({
  variable: "--font-dm-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "REZN · Music Control Room",
  description: "REZN Control Room — generate, curate, and refine original tracks.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      {/* Dark theme is the default on load; ThemeToggle swaps this class. */}
      <body
        className={`theme-dark ${display.variable} ${body.variable} ${dmMono.variable} antialiased`}
      >
        <CopilotKit runtimeUrl="/api/copilotkit" showDevConsole={false} enableInspector={false}>
          {children}
        </CopilotKit>
      </body>
    </html>
  );
}
