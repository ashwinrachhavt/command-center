import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });
export const metadata: Metadata = {
  title: { default: "Command Center", template: "%s · Command Center" },
  description:
    "Your opportunities, relationships and agents. One focused workspace.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <ClerkProvider
      signInUrl="/sign-in"
      signUpUrl="/sign-up"
      signInFallbackRedirectUrl="/"
      signUpFallbackRedirectUrl="/"
      appearance={{
        variables: {
          colorPrimary: "var(--primary)",
          colorBackground: "var(--card)",
          colorForeground: "var(--foreground)",
          colorMutedForeground: "var(--muted-foreground)",
          colorInput: "var(--background)",
          colorInputForeground: "var(--foreground)",
          borderRadius: "8px",
          fontFamily: "inherit",
        },
      }}
    >
      <html lang="en" className={geist.variable} suppressHydrationWarning>
        <body>
          <script
            dangerouslySetInnerHTML={{
              __html: `try{var p=localStorage.getItem('command-center:palette');if(['graphite','teal','blue','violet'].includes(p))document.documentElement.dataset.palette=p}catch{}`,
            }}
          />
          <Providers>{children}</Providers>
        </body>
      </html>
    </ClerkProvider>
  );
}
