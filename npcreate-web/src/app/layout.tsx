import type { Metadata } from "next";
import { Inter, Plus_Jakarta_Sans, Noto_Sans_Thai } from "next/font/google";
import "./globals.css";
import { Navbar } from "@/components/public/Navbar";
import { Footer } from "@/components/public/Footer";
import { FloatingLineButton } from "@/components/public/FloatingLineButton";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-jakarta",
});

const notoThai = Noto_Sans_Thai({
  subsets: ["thai"],
  variable: "--font-thai",
});

export const metadata: Metadata = {
  title: {
    default: "NP Create — รับยิงแอด GMV Max & TikTok Shop",
    template: "%s | NP Create",
  },
  description: "ปั้นยอดขาย TikTok Shop ของคุณให้โต 10 เท่าด้วย GMV Max ผลงานพิสูจน์แล้วกับ 50+ แบรนด์ ยอดขายรวมทะลุ 100 ล้านบาท",
  keywords: ["รับยิงแอด GMV Max", "TikTok Shop", "ยิงแอด TikTok", "การตลาดออนไลน์", "NP Create"],
  authors: [{ name: "NP Create" }],
  openGraph: {
    type: "website",
    locale: "th_TH",
    url: "https://npcreate.co.th",
    siteName: "NP Create",
    title: "NP Create — รับยิงแอด GMV Max & TikTok Shop",
    description: "ปั้นยอดขาย TikTok Shop ของคุณให้โต 10 เท่าด้วย GMV Max",
  },
  robots: {
    index: true,
    follow: true,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="th" suppressHydrationWarning>
      <body className={`${inter.variable} ${jakarta.variable} ${notoThai.variable} font-sans antialiased`}>
        <Navbar />
        {children}
        <Footer />
        <FloatingLineButton />
      </body>
    </html>
  );
}