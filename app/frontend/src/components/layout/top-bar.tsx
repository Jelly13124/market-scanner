import { UserMenu } from '@/components/auth/user-menu';
import { LanguageToggle } from '@/components/language-toggle';

interface TopBarProps {
  onSettingsClick: () => void;
}

export function TopBar({ onSettingsClick }: TopBarProps) {
  return (
    <div className="absolute top-0 right-0 z-40 flex items-center gap-0 py-1 px-2 bg-panel/80">
      {/* Language toggle (Phase 7 i18n) */}
      <LanguageToggle />

      {/* Account menu (Wave 7 multi-tenant auth) — Settings now lives inside */}
      <UserMenu onSettingsClick={onSettingsClick} />
    </div>
  );
}
