import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HireFlow",
  description: "Evidence-based candidate screening",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full bg-canvas text-ink-900 antialiased">{children}</body>
    </html>
  );
}
