import type { Metadata } from "next";
import {
  Instrument_Serif,
  Plus_Jakarta_Sans,
  Spline_Sans_Mono,
} from "next/font/google";
import "./globals.css";
import "@copilotkit/react-core/v2/styles.css";

const plusJakartaSans = Plus_Jakarta_Sans({
  variable: "--font-plus-jakarta-sans",
  subsets: ["latin"],
});

const splineSansMono = Spline_Sans_Mono({
  variable: "--font-spline-sans-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const instrumentSerif = Instrument_Serif({
  variable: "--font-instrument-serif",
  subsets: ["latin"],
  weight: "400",
});

export const metadata: Metadata = {
  title: "MarketMesh",
  description: "An open A2A commerce exchange",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${plusJakartaSans.variable} ${splineSansMono.variable} ${instrumentSerif.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
