// =============================================================================
// SOLVEREIGN Platform Layout (URL: /platform/*)
// =============================================================================
// Simple pass-through layout. Auth is handled per-page.
// Login page is public, home page requires auth.
// =============================================================================

interface PlatformLayoutProps {
  children: React.ReactNode;
}

export default function PlatformLayout({ children }: PlatformLayoutProps) {
  // No auth check here - let individual pages handle their own auth
  // This allows /platform/login to be public while /platform/home can check auth
  return <>{children}</>;
}
