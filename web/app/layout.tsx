import type { Metadata, Viewport } from "next";
import { Archivo, Big_Shoulders } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

const archivo = Archivo({
  subsets: ["latin"],
  variable: "--font-archivo",
  axes: ["wdth"],
  display: "swap",
});

const shoulders = Big_Shoulders({
  subsets: ["latin"],
  variable: "--font-shoulders",
  axes: ["opsz"],
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Rolecall: fresh tech roles, matched to you", template: "%s · Rolecall" },
  description:
    "Rolecall crawls thousands of fresh tech roles every day and ranks them against your resume, with a reason for every match. Internships and new-grad roles across India and remote.",
  applicationName: "Rolecall",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#08160f" },
    { media: "(prefers-color-scheme: light)", color: "#f3f7f2" },
  ],
};

// Runs before paint so the saved or system theme never flashes.
const themeScript = `(function(){try{var t=localStorage.getItem('theme');if(!t){t=matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'}document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme='dark'}})()`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-IN" className={`${archivo.variable} ${shoulders.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-dvh">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
