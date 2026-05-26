// Phase 7 i18n: i18next bootstrap.
//
// Loaded once by main.tsx (top of import chain). Initializes the
// singleton i18n instance with two languages (en/zh), browser-language
// detection + localStorage cache, and the locale resources statically
// imported below so there's no async lazy-load on first render.

import i18n from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { initReactI18next } from 'react-i18next';

import en from './locales/en.json';
import zh from './locales/zh.json';

export const SUPPORTED_LANGUAGES = ['en', 'zh'] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      zh: { translation: zh },
    },
    fallbackLng: 'en',
    interpolation: { escapeValue: false }, // React already escapes
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: 'ui-language',
      caches: ['localStorage'],
    },
  });

export default i18n;
