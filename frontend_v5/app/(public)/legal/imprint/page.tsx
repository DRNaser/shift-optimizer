/**
 * Imprint / Impressum (P0.3)
 * ==========================
 *
 * Required by Austrian/German law (§ 5 ECG / § 5 TMG).
 * Last updated: 2026-01-11
 * Version: 1.0.0
 */

import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Impressum | SOLVEREIGN',
  description: 'Impressum und rechtliche Informationen zu SOLVEREIGN',
};

export default function ImprintPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto py-12 px-4 sm:px-6 lg:px-8">
        <div className="bg-white shadow rounded-lg p-8">
          {/* Header */}
          <div className="border-b pb-6 mb-8">
            <h1 className="text-3xl font-bold text-gray-900">
              Impressum
            </h1>
            <p className="mt-2 text-sm text-gray-500">
              Informationen gemäß § 5 ECG und § 25 MedienG
            </p>
          </div>

          {/* Content */}
          <div className="prose prose-gray max-w-none">
            <h2>Angaben zum Unternehmen</h2>
            <address className="not-italic">
              <strong>SOLVEREIGN GmbH</strong><br />
              [Adresse wird ergänzt]<br />
              1XXX Wien<br />
              Österreich
            </address>

            <h3>Kontakt</h3>
            <p>
              E-Mail: <a href="mailto:info@solvereign.com">info@solvereign.com</a><br />
              Telefon: [wird ergänzt]
            </p>

            <h3>Unternehmensgegenstand</h3>
            <p>
              Entwicklung und Betrieb von Software-as-a-Service Lösungen
              für die Schichtplanung und Logistikoptimierung.
            </p>

            <h3>Firmenbuchdaten</h3>
            <p>
              Firmenbuchnummer: FN XXXXXX x<br />
              Firmenbuchgericht: Handelsgericht Wien<br />
              UID-Nummer: ATU XXXXXXXX
            </p>

            <h3>Geschäftsführung</h3>
            <p>[Name des Geschäftsführers wird ergänzt]</p>

            <h2>Aufsichtsbehörde</h2>
            <p>
              Bezirkshauptmannschaft [wird ergänzt] / Magistrat Wien
            </p>

            <h2>Berufsrecht</h2>
            <p>
              Gewerbeordnung: <a href="https://www.ris.bka.gv.at" target="_blank" rel="noopener noreferrer">www.ris.bka.gv.at</a>
            </p>

            <h2>Verbraucherstreitbeilegung</h2>
            <p>
              Die Europäische Kommission stellt eine Plattform zur
              Online-Streitbeilegung (OS) bereit:{' '}
              <a href="https://ec.europa.eu/consumers/odr" target="_blank" rel="noopener noreferrer">
                https://ec.europa.eu/consumers/odr
              </a>
            </p>
            <p>
              Wir sind nicht bereit oder verpflichtet, an Streitbeilegungsverfahren
              vor einer Verbraucherschlichtungsstelle teilzunehmen.
            </p>

            <h2>Haftungshinweis</h2>
            <h3>Haftung für Inhalte</h3>
            <p>
              Die Inhalte unserer Seiten wurden mit größter Sorgfalt erstellt.
              Für die Richtigkeit, Vollständigkeit und Aktualität der Inhalte
              können wir jedoch keine Gewähr übernehmen.
            </p>

            <h3>Haftung für Links</h3>
            <p>
              Unser Angebot enthält Links zu externen Webseiten Dritter, auf deren
              Inhalte wir keinen Einfluss haben. Für die Inhalte der verlinkten
              Seiten ist stets der jeweilige Anbieter oder Betreiber der Seiten
              verantwortlich.
            </p>

            <h2>Urheberrecht</h2>
            <p>
              Die durch die Seitenbetreiber erstellten Inhalte und Werke auf
              diesen Seiten unterliegen dem österreichischen Urheberrecht.
              Die Vervielfältigung, Bearbeitung, Verbreitung und jede Art der
              Verwertung außerhalb der Grenzen des Urheberrechts bedürfen der
              schriftlichen Zustimmung des jeweiligen Autors bzw. Erstellers.
            </p>

            <h2>Bildnachweise</h2>
            <p>
              Icons: Lucide Icons (MIT License)<br />
              UI Components: shadcn/ui (MIT License)
            </p>
          </div>

          {/* Footer */}
          <div className="mt-12 pt-6 border-t">
            <div className="flex flex-col sm:flex-row justify-between items-center gap-4">
              <div className="text-sm text-gray-500">
                Allgemeine Anfragen:{' '}
                <a href="mailto:info@solvereign.com" className="text-blue-600 hover:underline">
                  info@solvereign.com
                </a>
              </div>
              <div className="flex gap-4 text-sm">
                <Link href="/legal/terms" className="text-gray-600 hover:text-gray-900">
                  AGB
                </Link>
                <Link href="/legal/privacy" className="text-gray-600 hover:text-gray-900">
                  Datenschutz
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
