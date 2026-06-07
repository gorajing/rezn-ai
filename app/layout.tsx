import type { Metadata } from "next";
import { DM_Mono } from "next/font/google";
import { CopilotKit } from "@copilotkit/react-core";
import "@copilotkit/react-ui/styles.css";
import "./globals.css";

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
      <body className={`theme-dark ${dmMono.variable} antialiased`}>
        <CopilotKit runtimeUrl="/api/copilotkit">{children}</CopilotKit>
      </body>
    </html>
  );
}
