import type { Metadata } from "next";
import "./globals.css";
import { AppProvider } from "@/lib/store";
import { AuthGate, AuthProvider } from "@/lib/auth";
import Navbar from "@/components/ui/Navbar";

export const metadata: Metadata = {
  title: "TikTok Automate - Short-Form Repurposing Studio",
  description: "Turn approved source videos into edited short-form variants with captions, covers, and export-ready assets",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased dark">
      <body className="min-h-full bg-gray-950 text-gray-100 flex flex-col">
        <AuthProvider>
          <Navbar />
          <AuthGate>
            <AppProvider>
              <main className="flex-1 max-w-7xl mx-auto w-full px-4 py-6">
                {children}
              </main>
            </AppProvider>
          </AuthGate>
        </AuthProvider>
      </body>
    </html>
  );
}
