import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VoiceQA",
  description: "Call quality & compliance",
};

// Set the theme class before first paint to avoid a flash. Default = light.
const noFlashTheme = `(function(){try{var t=localStorage.getItem("theme");if(t==="dark")document.documentElement.classList.add("dark");}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: noFlashTheme }} />
      </head>
      <body className="antialiased">{children}</body>
    </html>
  );
}
