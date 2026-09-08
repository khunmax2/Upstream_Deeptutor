import { afterEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_BRAND } from '@/lib/brand/brand-config';

/**
 * This file asserted the upstream identity — `OpenMAIC`, `/openmaic-mark.png`,
 * `#722ed1` — and kept asserting it after the fork replaced those defaults, so
 * it has been red since the de-branding change rather than guarding anything.
 * It now asserts what this build actually ships.
 */

const originalEnv = process.env.NEXT_PUBLIC_BASE_PATH;

afterEach(() => {
  if (originalEnv === undefined) delete process.env.NEXT_PUBLIC_BASE_PATH;
  else process.env.NEXT_PUBLIC_BASE_PATH = originalEnv;
});

describe('DEFAULT_BRAND (single-brand build)', () => {
  it('is the host product, not the upstream one', () => {
    expect(DEFAULT_BRAND.productName).toBe('DeepWitya');
    expect(DEFAULT_BRAND.shortName).toBe('DeepWitya');
    expect(DEFAULT_BRAND.markSrc).toBe('/brand-mark.png');
    expect(DEFAULT_BRAND.themeColor).toBe('#b0501e');
    expect(DEFAULT_BRAND.tagline).toBe('Agent-Native Learning');
  });

  it('marks its horizontal logo as already containing the wordmark', () => {
    expect(DEFAULT_BRAND.logoHasWordmark).toBe(true);
    expect(DEFAULT_BRAND.logoSrc).toBe('/brand-wordmark.png');
  });

  it('prefixes both assets when the app is served under a subpath', async () => {
    // Root-absolute /public paths are the one thing Next's basePath does not
    // prefix, and the logo is the most visible casualty when it is missed.
    vi.resetModules();
    process.env.NEXT_PUBLIC_BASE_PATH = '/course-studio-app';
    const { DEFAULT_BRAND: prefixed } = await import('@/lib/brand/brand-config');

    expect(prefixed.logoSrc).toBe('/course-studio-app/brand-wordmark.png');
    expect(prefixed.markSrc).toBe('/course-studio-app/brand-mark.png');
    expect(prefixed.productName).toBe('DeepWitya'); // not a path; untouched
  });
});
