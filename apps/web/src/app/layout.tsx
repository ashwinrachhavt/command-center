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
          colorPrimary: "#42c7a1",
          colorBackground: "#191b1c",
          colorForeground: "#f2f3f3",
          colorMutedForeground: "#9ca3a6",
          colorInput: "#121415",
          colorInputForeground: "#f2f3f3",
          borderRadius: "8px",
          fontFamily: "inherit",
        },
      }}
    >
      <html lang="en" className={`dark ${geist.variable}`}>
        <body>
          <Providers>{children}</Providers>
        </body>
      </html>
    </ClerkProvider>
  );
}
