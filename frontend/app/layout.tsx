import type { Metadata } from "next";
import type { ReactNode } from "react";
import Nav from "@/components/nav";
import Providers from "./providers";
import "./globals.css";

export const metadata: Metadata = { title: "Document Intelligence", description: "Invoice extraction and review" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-GB">
      <body className="flex min-h-screen max-md:flex-col">
        <Providers>
          <Nav />
          <main className="min-w-0 flex-1 px-8 py-7 max-md:px-4">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
