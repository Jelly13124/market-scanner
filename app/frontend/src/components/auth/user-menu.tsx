// user-menu.tsx — top-bar account control. Shows the signed-in user's
// name/email and a Logout button. Mounted in the authed layout's TopBar.

import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { useAuth } from '@/contexts/auth-context';
import { LogOut, User as UserIcon } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

export function UserMenu() {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  if (!user) return null;

  const label = user.full_name?.trim() || user.email;

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
          title={label}
        >
          <UserIcon size={16} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-2">
        <div className="px-2 py-1.5">
          {user.full_name && (
            <p className="text-sm font-medium leading-tight truncate">
              {user.full_name}
            </p>
          )}
          <p className="text-xs text-muted-foreground truncate">{user.email}</p>
        </div>
        <div className="my-1 h-px bg-border" />
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
