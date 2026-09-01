import type { Metadata } from "next";
import "./globals.css";

const SITE_URL = "https://wlsn.me";
const SITE_NAME = "James Wilson";
const PAGE_TITLE = "Australia GDP nowcast";
// MODEL-NEUTRAL, BECAUSE IT IS SITE-WIDE. This described v2's method — "an
// RBA-style Monthly Activity Indicator and MIDAS regression" — while `/` now
// serves v3 and `/v2` serves v2, so it was about to be wrong on the homepage
// and right only on a secondary route. Search results and link previews would
// have described the wrong model. Naming the job rather than the method is
// true of both and survives the next cutover.
const PAGE_DESCRIPTION =
  "Weekly nowcast of Australian GDP growth, published before the ABS releases the official figure.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: PAGE_TITLE,
  description: PAGE_DESCRIPTION,
  applicationName: SITE_NAME,
  authors: [{ name: SITE_NAME, url: SITE_URL }],
  creator: SITE_NAME,
  robots: { index: true, follow: true },
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: SITE_NAME,
    title: PAGE_TITLE,
    description: PAGE_DESCRIPTION,
    locale: "en_AU",
  },
  twitter: {
    card: "summary",
    title: PAGE_TITLE,
    description: PAGE_DESCRIPTION,
  },
};

const websiteJsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: SITE_NAME,
  alternateName: PAGE_TITLE,
  url: SITE_URL,
  author: {
    "@type": "Person",
    name: SITE_NAME,
    url: SITE_URL,
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(websiteJsonLd) }}
        />
      </head>
      <body className="font-body antialiased">{children}</body>
    </html>
  );
}
