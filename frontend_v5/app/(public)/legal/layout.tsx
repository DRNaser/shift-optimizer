/**
 * Legal Pages Layout (P0.3)
 * =========================
 *
 * Shared layout for all legal pages (Terms, Privacy, Imprint).
 */

import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  robots: 'noindex, follow',
};

export default function LegalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <Link href="/" className="flex items-center space-x-2">
              <span className="text-xl font-bold text-gray-900">SOLVEREIGN</span>
            </Link>
            <nav className="flex space-x-4 text-sm">
              <Link
                href="/legal/terms"
                className="text-gray-600 hover:text-gray-900"
              >
                AGB
              </Link>
              <Link
                href="/legal/privacy"
                className="text-gray-600 hover:text-gray-900"
              >
                Datenschutz
              </Link>
              <Link
                href="/legal/imprint"
                className="text-gray-600 hover:text-gray-900"
              >
                Impressum
              </Link>
            </nav>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="flex-grow">
        {children}
      </main>

      {/* Footer */}
      <footer className="bg-gray-100 border-t">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col md:flex-row justify-between items-center gap-4">
            <p className="text-sm text-gray-500">
              &copy; {new Date().getFullYear()} SOLVEREIGN GmbH. Alle Rechte vorbehalten.
            </p>
            <div className="flex space-x-6 text-sm text-gray-500">
              <Link href="/platform/login" className="hover:text-gray-900">
                Login
              </Link>
              <a href="mailto:support@solvereign.com" className="hover:text-gray-900">
                Support
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
