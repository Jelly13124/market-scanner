// user-menu.tsx — top-bar account control. Shows the signed-in user's
// avatar/name/email, a Settings item, and a Logout button.
// Mounted in the authed layout's TopBar.

import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { useAuth } from '@/contexts/auth-context';
import { LogOut, Settings, User as UserIcon } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

interface UserMenuProps {
  onSettingsClick?: () => void;
}

export function UserMenu({ onSettingsClick }: UserMenuProps) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  if (!user) return null;

  const name = user.full_name?.trim() || user.email;
  const initial = (user.full_name?.trim() || user.email).charAt(0).toUpperCase();

  const handleSettings = () => {
    setOpen(false);
    onSettingsClick?.();
  };

  const handleLogout = async () => {
    setOpen(false);
    await logout();
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground hover:bg-ramp-grey-700 transition-colors"
          aria-label={t('auth.account', 'Account')}
          title={name}
        >
          <UserIcon size={16} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-2">
        {/* Header: avatar + name (+ admin badge) + email */}
        <div className="flex items-center gap-2 px-2 py-1.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary text-sm font-medium">
            {initial}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <p className="text-sm font-medium leading-tight truncate">{name}</p>
              {user.is_superuser && (
                <span className="shrink-0 rounded bg-primary/10 px-1 py-0.5 text-[9px] font-medium uppercase text-primary">
                  {t('auth.admin', 'Admin')}
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground truncate">{user.email}</p>
          </div>
        </div>
        <div className="my-1 h-px bg-border" />
        <button
          type="button"
          onClick={handleSettings}
          className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-left hover:bg-accent/40"
        >
          <Settings size={14} />
          {t('tabs.settings', 'Settings')}
        </button>
        <button
          type="button"
          onClick={handleLogout}
          className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-left hover:bg-accent/40"
        >
          <LogOut size={14} />
          {t('auth.logout', 'Log out')}
        </button>
      </PopoverContent>
    </Popover>
  );
}
