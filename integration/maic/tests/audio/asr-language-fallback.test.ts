import { describe, expect, it } from 'vitest';

import { ASR_PROVIDERS, fallbackASRLanguage } from '@/lib/audio/constants';

describe('fallbackASRLanguage', () => {
  it('prefers auto wherever a provider offers it', () => {
    expect(fallbackASRLanguage('th', ['auto', 'zh', 'en'])).toBe('auto');
    // Even when the requested language is itself on offer: letting the
    // recogniser decide is right for every reader, and this is only reached
    // when the current choice was rejected anyway.
    expect(fallbackASRLanguage('zh', ['auto', 'zh'])).toBe('auto');
  });

  it('keeps the language when a provider spells it differently', () => {
    // The regression this exists for: browser-native lists th-TH and no auto,
    // and used to answer zh-CN because that is simply first in its array.
    expect(fallbackASRLanguage('th', ['zh-CN', 'en-US', 'th-TH'])).toBe('th-TH');
    expect(fallbackASRLanguage('th-TH', ['zh-CN', 'th'])).toBe('th');
    expect(fallbackASRLanguage('EN-gb', ['zh-CN', 'en-US'])).toBe('en-US');
  });

  it('falls back to the first offered only when nothing matches', () => {
    expect(fallbackASRLanguage('th', ['zh-CN', 'en-US'])).toBe('zh-CN');
    expect(fallbackASRLanguage('', [])).toBe('auto');
  });

  it('never lands a Thai reader on Chinese with the real provider table', () => {
    for (const [id, provider] of Object.entries(ASR_PROVIDERS)) {
      const supported = provider.supportedLanguages ?? [];
      if (!supported.length) continue;
      const picked = fallbackASRLanguage('th', supported);
      const isChinese = picked.toLowerCase().startsWith('zh') || picked.toLowerCase().startsWith('yue');
      // A provider that genuinely cannot do Thai and offers no auto may still
      // land on its first entry — that is honest. What must not happen is
      // choosing Chinese while Thai or auto was available.
      const hadBetter = supported.includes('auto') || supported.some((c) => c.toLowerCase().startsWith('th'));
      expect(isChinese && hadBetter, `${id} chose ${picked}`).toBe(false);
    }
  });
});
