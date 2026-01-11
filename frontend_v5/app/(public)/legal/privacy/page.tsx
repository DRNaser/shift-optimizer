/**
 * Privacy Policy / Datenschutzerklärung (P0.3)
 * =============================================
 *
 * GDPR-compliant privacy policy for DACH market.
 * Last updated: 2026-01-11
 * Version: 1.0.0
 */

import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Datenschutzerklärung | SOLVEREIGN',
  description: 'Informationen zum Datenschutz bei SOLVEREIGN',
};

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-4xl mx-auto py-12 px-4 sm:px-6 lg:px-8">
        <div className="bg-white shadow rounded-lg p-8">
          {/* Header */}
          <div className="border-b pb-6 mb-8">
            <h1 className="text-3xl font-bold text-gray-900">
              Datenschutzerklärung
            </h1>
            <p className="mt-2 text-sm text-gray-500">
              Version 1.0.0 | Stand: 11. Januar 2026
            </p>
          </div>

          {/* Content */}
          <div className="prose prose-gray max-w-none">
            <h2>1. Verantwortlicher</h2>
            <p>
              Verantwortlich für die Datenverarbeitung auf dieser Plattform ist:
            </p>
            <address className="not-italic">
              SOLVEREIGN GmbH<br />
              [Adresse wird ergänzt]<br />
              Wien, Österreich<br />
              E-Mail: privacy@solvereign.com
            </address>

            <h2>2. Datenschutzbeauftragter</h2>
            <p>
              Bei Fragen zum Datenschutz erreichen Sie unseren
              Datenschutzbeauftragten unter: dpo@solvereign.com
            </p>

            <h2>3. Erhobene Daten</h2>
            <h3>3.1 Nutzerkonto</h3>
            <p>Bei der Registrierung erheben wir:</p>
            <ul>
              <li>E-Mail-Adresse</li>
              <li>Name</li>
              <li>Unternehmenszugehörigkeit</li>
              <li>Rolle/Berechtigung</li>
            </ul>

            <h3>3.2 Schichtplanungsdaten</h3>
            <p>Im Rahmen der Plattformnutzung werden verarbeitet:</p>
            <ul>
              <li>Fahrernamen und Personalnummern</li>
              <li>Kontaktdaten (Telefon, E-Mail) für Benachrichtigungen</li>
              <li>Arbeitszeitdaten und Schichtpläne</li>
              <li>Standortinformationen (Abholpunkte, Routen)</li>
            </ul>

            <h3>3.3 Technische Daten</h3>
            <p>Automatisch erfasst werden:</p>
            <ul>
              <li>IP-Adresse (anonymisiert nach 7 Tagen)</li>
              <li>Browser-Typ und -Version</li>
              <li>Zugriffszeitpunkte</li>
              <li>Fehlerprotokolle (ohne personenbezogene Daten)</li>
            </ul>

            <h2>4. Zwecke der Verarbeitung</h2>
            <p>Wir verarbeiten Ihre Daten für folgende Zwecke:</p>
            <ul>
              <li>
                <strong>Vertragserfüllung (Art. 6 Abs. 1 lit. b DSGVO):</strong>{' '}
                Bereitstellung der Schichtplanungsfunktionen
              </li>
              <li>
                <strong>Berechtigtes Interesse (Art. 6 Abs. 1 lit. f DSGVO):</strong>{' '}
                Verbesserung unserer Dienste, Fehlerbehebung
              </li>
              <li>
                <strong>Rechtliche Verpflichtung (Art. 6 Abs. 1 lit. c DSGVO):</strong>{' '}
                Erfüllung gesetzlicher Aufbewahrungspflichten
              </li>
            </ul>

            <h2>5. Empfänger der Daten</h2>
            <h3>5.1 Auftragsverarbeiter</h3>
            <p>Wir setzen folgende Dienstleister ein:</p>
            <ul>
              <li>
                <strong>Cloud-Hosting:</strong> AWS (Frankfurt, eu-central-1) -
                Infrastruktur und Datenbanken
              </li>
              <li>
                <strong>E-Mail-Versand:</strong> SendGrid - Benachrichtigungen
              </li>
              <li>
                <strong>Fehlerüberwachung:</strong> Sentry - Anonymisierte Fehlerberichte
              </li>
            </ul>
            <p>
              Mit allen Auftragsverarbeitern bestehen
              Auftragsverarbeitungsverträge gemäß Art. 28 DSGVO.
            </p>

            <h3>5.2 Keine Weitergabe an Dritte</h3>
            <p>
              Eine Weitergabe Ihrer Daten an Dritte erfolgt nur, wenn dies zur
              Vertragserfüllung erforderlich ist oder Sie ausdrücklich eingewilligt haben.
            </p>

            <h2>6. Speicherdauer</h2>
            <table className="min-w-full">
              <thead>
                <tr>
                  <th className="text-left">Datenkategorie</th>
                  <th className="text-left">Speicherdauer</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Nutzerkonto</td>
                  <td>Bis zur Löschung + 30 Tage Backup</td>
                </tr>
                <tr>
                  <td>Schichtpläne</td>
                  <td>7 Jahre (arbeitsrechtliche Aufbewahrung)</td>
                </tr>
                <tr>
                  <td>Audit-Logs</td>
                  <td>3 Jahre</td>
                </tr>
                <tr>
                  <td>Server-Logs</td>
                  <td>90 Tage</td>
                </tr>
              </tbody>
            </table>

            <h2>7. Ihre Rechte</h2>
            <p>Sie haben folgende Rechte bezüglich Ihrer personenbezogenen Daten:</p>
            <ul>
              <li>
                <strong>Auskunft (Art. 15 DSGVO):</strong> Welche Daten wir über
                Sie gespeichert haben
              </li>
              <li>
                <strong>Berichtigung (Art. 16 DSGVO):</strong> Korrektur
                unrichtiger Daten
              </li>
              <li>
                <strong>Löschung (Art. 17 DSGVO):</strong> Löschung Ihrer Daten,
                soweit keine Aufbewahrungspflicht besteht
              </li>
              <li>
                <strong>Einschränkung (Art. 18 DSGVO):</strong> Einschränkung
                der Verarbeitung
              </li>
              <li>
                <strong>Datenübertragbarkeit (Art. 20 DSGVO):</strong> Export
                Ihrer Daten in maschinenlesbarem Format
              </li>
              <li>
                <strong>Widerspruch (Art. 21 DSGVO):</strong> Widerspruch gegen
                Verarbeitung auf Basis berechtigter Interessen
              </li>
            </ul>
            <p>
              Zur Ausübung Ihrer Rechte kontaktieren Sie uns unter:{' '}
              <a href="mailto:privacy@solvereign.com">privacy@solvereign.com</a>
            </p>

            <h2>8. Beschwerderecht</h2>
            <p>
              Sie haben das Recht, sich bei einer Datenschutz-Aufsichtsbehörde
              zu beschweren. Zuständige Behörde in Österreich:
            </p>
            <address className="not-italic">
              Österreichische Datenschutzbehörde<br />
              Barichgasse 40-42<br />
              1030 Wien<br />
              <a href="https://www.dsb.gv.at">www.dsb.gv.at</a>
            </address>

            <h2>9. Cookies und Tracking</h2>
            <h3>9.1 Technisch notwendige Cookies</h3>
            <p>Wir verwenden folgende notwendige Cookies:</p>
            <ul>
              <li>
                <code>admin_session</code>: Authentifizierung (HttpOnly, Secure)
              </li>
              <li>
                <code>portal_session</code>: Fahrer-Portal-Session (HttpOnly, Secure)
              </li>
            </ul>

            <h3>9.2 Kein Tracking</h3>
            <p>
              Wir verwenden keine Tracking-Cookies, keine Werbecookies und kein
              Cross-Site-Tracking. Es werden keine Daten an Werbenetzwerke übermittelt.
            </p>

            <h2>10. Datensicherheit</h2>
            <p>Wir setzen folgende Sicherheitsmaßnahmen ein:</p>
            <ul>
              <li>TLS 1.3 Verschlüsselung für alle Verbindungen</li>
              <li>AES-256 Verschlüsselung für gespeicherte Daten</li>
              <li>Multi-Tenant-Isolation auf Datenbankebene</li>
              <li>Regelmäßige Sicherheitsaudits</li>
              <li>Zugriffskontrollen nach dem Prinzip der minimalen Rechte</li>
            </ul>

            <h2>11. Internationale Datenübermittlung</h2>
            <p>
              Alle Daten werden ausschließlich in der EU (AWS Frankfurt)
              verarbeitet. Es findet keine Übermittlung in Drittländer statt.
            </p>

            <h2>12. Änderungen dieser Erklärung</h2>
            <p>
              Diese Datenschutzerklärung wird bei Bedarf aktualisiert. Wesentliche
              Änderungen werden Ihnen per E-Mail mitgeteilt.
            </p>
          </div>

          {/* Footer */}
          <div className="mt-12 pt-6 border-t">
            <div className="flex flex-col sm:flex-row justify-between items-center gap-4">
              <div className="text-sm text-gray-500">
                Fragen zum Datenschutz:{' '}
                <a href="mailto:privacy@solvereign.com" className="text-blue-600 hover:underline">
                  privacy@solvereign.com
                </a>
              </div>
              <div className="flex gap-4 text-sm">
                <Link href="/legal/terms" className="text-gray-600 hover:text-gray-900">
                  AGB
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
