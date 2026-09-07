import { supportedLocales } from './locales';

export type Locale = (typeof supportedLocales)[number]['code'];

// i18next reads this as both `lng` and `fallbackLng`, so it is the first
// paint AND what any key missing from a locale degrades to. English is the
// language every locale file is written against, and the one a reader who
// matched no locale is most likely to follow.
export const defaultLocale: Locale = 'en-US';
