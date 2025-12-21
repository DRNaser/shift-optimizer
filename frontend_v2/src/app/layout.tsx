import './globals.css';
import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import type { ReactNode } from 'react';
import Link from 'next/link';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
    title: 'ShiftOptimizer v2.0',
    description: 'Deterministic weekly shift optimizer for Last-Mile-Delivery',
};

export default function RootLayout({ children }: { children: ReactNode }) {
    return (
        <html lang="en">
            <body className={inter.className}>
                <div className="min-h-screen bg-background">
                    <header className="border-b">
                        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center">
                                    <span className="text-primary-foreground font-bold text-lg">S</span>
                                </div>
                                <span className="font-semibold text-lg">ShiftOptimizer</span>
                                <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">v2.0</span>
                            </div>
                            <nav className="flex items-center gap-4">
                                <Link href="/" className="text-sm text-muted-foreground hover:text-foreground transition-colors">
                                    Setup
                                </Link>
                            </nav>
                        </div>
                    </header>
                    <main className="container mx-auto px-4 py-8">
                        {children}
                    </main>
                </div>
            </body>
        </html>
    );
}
