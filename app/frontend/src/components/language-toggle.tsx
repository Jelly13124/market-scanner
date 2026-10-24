// Phase 7 i18n — global UI language toggle. Mounted in the TopBar.
// Uses Popover (DropdownMenu not installed in this project's shadcn set).

import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { SUPPORTED_LANGUAGES, type SupportedLanguage } from '@/i18n';
import { Languages } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

const LANG_LABELS: Record<SupportedLanguage, string> = {
  en: 'English',
  zh: '简体中文',
};

export function LanguageToggle() {
  const { i18n, t } = useTranslation();
  const [open, setOpen] = useState(false);
  const current = (i18n.resolvedLanguage || i18n.language || 'en').slice(0, 2) as SupportedLanguage;

  const pick = (lng: SupportedLanguage) => {
    void i18n.changeLanguage(lng);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground hover:bg-ramp-grey-700 transition-colors"
          aria-label={t('topBar.language')}
          title={t('topBar.language')}
        >
          <Languages size={16} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-40 p-1">
        {SUPPORTED_LANGUAGES.map((lng) => (
          <button
            key={lng}
            type="button"
            onClick={() => pick(lng)}
            className={cn(
              'w-full text-left px-3 py-2 text-sm rounded hover:bg-accent/40',
              current === lng && 'bg-accent/30 font-medium',
            )}
          >
            {LANG_LABELS[lng]}
            {current === lng && <span className="ml-2 text-xs text-muted-foreground">●</span>}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}
