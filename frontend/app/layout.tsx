import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Lead Agent",
  description: "AI-powered lead generation platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
