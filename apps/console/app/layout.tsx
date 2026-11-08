import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata, Viewport } from "next";
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
  title: "MarketMesh — open agent exchange",
  description:
    "Independent buyer and seller agents discover, negotiate, and transact with a human at the order gate.",
};

export const viewport: Viewport = {
  themeColor: "#f4f0e6",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${plusJakartaSans.variable} ${splineSansMono.variable} ${instrumentSerif.variable} antialiased`}
        suppressHydrationWarning
      >
        {/* Bitdefender / SafePay inject bis_skin_checked after SSR but
            before React hydrates. Strip early so hydration sees the
            server HTML unchanged. suppressHydrationWarning alone only
            covers one level, so internal Next divs still warn. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var rm=function(e){if(e&&e.nodeType===1&&e.removeAttribute)e.removeAttribute('bis_skin_checked')};var clean=function(){document.querySelectorAll('[bis_skin_checked]').forEach(rm)};clean();new MutationObserver(function(ms){for(var i=0;i<ms.length;i++){var m=ms[i];rm(m.target);if(m.addedNodes)for(var j=0;j<m.addedNodes.length;j++)rm(m.addedNodes[j])}}).observe(document.documentElement,{attributes:true,subtree:true,attributeFilter:['bis_skin_checked'],childList:true})}catch(e){}`,
          }}
        />
        <ClerkProvider>{children}</ClerkProvider>
      </body>
    </html>
  );
}
