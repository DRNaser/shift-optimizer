/**
 * Terms of Service / AGB (P0.3)
 * =============================
 *
 * Static legal page - version tracked via git.
 * Last updated: 2026-01-11
 * Version: 1.0.0
 */

import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Allgemeine Geschäftsbedingungen | SOLVEREIGN',
  description: 'AGB für die Nutzung der SOLVEREIGN Plattform',
};

export default function TermsOfServicePage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto py-12 px-4 sm:px-6 lg:px-8">
        <div className="bg-white shadow rounded-lg p-8">
          {/* Header */}
          <div className="border-b pb-6 mb-8">
            <h1 className="text-3xl font-bold text-gray-900">
              Allgemeine Geschäftsbedingungen (AGB)
            </h1>
            <p className="mt-2 text-sm text-gray-500">
              Version 1.0.0 | Stand: 11. Januar 2026
            </p>
          </div>

          {/* Content */}
          <div className="prose prose-gray max-w-none">
            <h2>1. Geltungsbereich</h2>
            <p>
              Diese Allgemeinen Geschäftsbedingungen gelten für alle Verträge zwischen
              SOLVEREIGN (nachfolgend "Anbieter") und dem Kunden (nachfolgend "Kunde")
              über die Nutzung der SOLVEREIGN SaaS-Plattform zur Schichtplanung und
              -optimierung (nachfolgend "Plattform").
            </p>

            <h2>2. Vertragsgegenstand</h2>
            <p>
              Der Anbieter stellt dem Kunden eine cloudbasierte Software-as-a-Service
              Lösung zur Verfügung, die folgende Funktionen umfasst:
            </p>
            <ul>
              <li>Import und Verwaltung von Schichtplänen</li>
              <li>Automatisierte Schichtoptimierung</li>
              <li>Fahrer-Portal zur Planbestätigung</li>
              <li>Export und Berichterstattung</li>
            </ul>

            <h2>3. Vertragsschluss</h2>
            <p>
              Der Vertrag kommt durch die Registrierung des Kunden auf der Plattform
              und die Bestätigung dieser AGB zustande. Bei Unternehmenskunden erfolgt
              der Vertragsschluss durch Unterzeichnung eines separaten Auftragsformulars.
            </p>

            <h2>4. Leistungsumfang</h2>
            <h3>4.1 Verfügbarkeit</h3>
            <p>
              Der Anbieter strebt eine Verfügbarkeit der Plattform von 99,5% im
              Monatsdurchschnitt an (exklusive geplanter Wartungsfenster).
            </p>

            <h3>4.2 Support</h3>
            <p>
              Der Anbieter bietet Support während der Geschäftszeiten
              (Mo-Fr 09:00-17:00 CET, außer österreichische Feiertage) per E-Mail.
            </p>

            <h2>5. Pflichten des Kunden</h2>
            <p>Der Kunde verpflichtet sich:</p>
            <ul>
              <li>Zugangsdaten vertraulich zu behandeln</li>
              <li>Die Plattform nur für legitime Geschäftszwecke zu nutzen</li>
              <li>Keine rechtswidrigen Inhalte hochzuladen</li>
              <li>Die anwendbaren Datenschutzgesetze einzuhalten</li>
            </ul>

            <h2>6. Vergütung</h2>
            <p>
              Die Vergütung richtet sich nach dem jeweils gültigen Preisverzeichnis
              oder dem individuellen Angebot. Rechnungen sind innerhalb von 14 Tagen
              nach Rechnungsdatum zur Zahlung fällig.
            </p>

            <h2>7. Datenschutz</h2>
            <p>
              Die Verarbeitung personenbezogener Daten erfolgt gemäß unserer{' '}
              <Link href="/legal/privacy" className="text-blue-600 hover:underline">
                Datenschutzerklärung
              </Link>{' '}
              und einem separaten Auftragsverarbeitungsvertrag (AVV).
            </p>

            <h2>8. Haftung</h2>
            <p>
              Die Haftung des Anbieters ist auf Vorsatz und grobe Fahrlässigkeit
              beschränkt. Bei leichter Fahrlässigkeit haftet der Anbieter nur für
              die Verletzung wesentlicher Vertragspflichten und ist auf den
              vorhersehbaren, vertragstypischen Schaden begrenzt.
            </p>

            <h2>9. Vertragslaufzeit und Kündigung</h2>
            <p>
              Der Vertrag wird auf unbestimmte Zeit geschlossen. Er kann von beiden
              Parteien mit einer Frist von 30 Tagen zum Monatsende gekündigt werden.
              Das Recht zur außerordentlichen Kündigung aus wichtigem Grund bleibt
              unberührt.
            </p>

            <h2>10. Änderungen der AGB</h2>
            <p>
              Der Anbieter behält sich vor, diese AGB mit angemessener Vorankündigung
              (mindestens 30 Tage) zu ändern. Widerspricht der Kunde nicht innerhalb
              von 14 Tagen nach Benachrichtigung, gelten die Änderungen als angenommen.
            </p>

            <h2>11. Schlussbestimmungen</h2>
            <p>
              Es gilt österreichisches Recht unter Ausschluss des UN-Kaufrechts.
              Gerichtsstand ist Wien, Österreich.
            </p>
            <p>
              Sollten einzelne Bestimmungen dieser AGB unwirksam sein, bleibt die
              Wirksamkeit der übrigen Bestimmungen unberührt.
            </p>
          </div>

          {/* Footer */}
          <div className="mt-12 pt-6 border-t">
            <div className="flex flex-col sm:flex-row justify-between items-center gap-4">
              <div className="text-sm text-gray-500">
                Bei Fragen kontaktieren Sie uns unter:{' '}
                <a href="mailto:legal@solvereign.com" className="text-blue-600 hover:underline">
                  legal@solvereign.com
                </a>
              </div>
              <div className="flex gap-4 text-sm">
                <Link href="/legal/privacy" className="text-gray-600 hover:text-gray-900">
                  Datenschutz
                </Link>
                <Link href="/legal/imprint" className="text-gray-600 hover:text-gray-900">
                  Impressum
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
