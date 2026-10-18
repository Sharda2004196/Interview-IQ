import type { Metadata } from "next";
import { Geist, Geist_Mono, Orbitron } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/ThemeProvider";
import { AppHeader } from "@/components/AppHeader";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

/* Display face for the wordmark + page headings. Orbitron is a variable
   Google font (wght 400–900, latin subset) that next/font downloads once at
   build time and self-hosts — no runtime request to fonts.gstatic.com. Every
   weight is real here, so font-semibold/font-bold are safe (note: the face it
   replaced was a single 500-weight glyph set, which is why the wordmark uses
   font-medium). */
const orbitron = Orbitron({
  variable: "--font-orbitron",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "InterviewIQ — AI Technical Interviewer",
  description: "Real-time technical interview simulator powered by Google ADK agents & Gemini Flash",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${orbitron.variable} antialiased bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 min-h-[100dvh] flex flex-col selection:bg-emerald-500/20 selection:text-emerald-400`}
      >
        <ThemeProvider>
          <AppHeader />
          <main className="flex-1 flex flex-col">{children}</main>
        </ThemeProvider>
      </body>
    </html>
  );
}
