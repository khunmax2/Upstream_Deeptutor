import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * The subpath bridge, tested at the two globals it patches.
 *
 * Worth testing rather than eyeballing: this is the one place that decides
 * where 74 `fetch('/api/...')` calls and three `EventSource`s actually go when
 * the app is served under a prefix, and getting it wrong does not look like a
 * network failure — it looks like an access-code login box nobody configured.
 */

const ORIGIN = 'https://host.example';
const PREFIX = '/course-studio-app';

type FakeWindow = {
  location: { origin: string; href: string };
  fetch: (input: unknown, init?: unknown) => Promise<string>;
  EventSource: new (url: string | URL, init?: unknown) => { url: string };
};

function makeWindow() {
  const fetched: string[] = [];
  const streamed: string[] = [];

  class FakeEventSource {
    url: string;
    constructor(url: string | URL) {
      this.url = String(url);
      streamed.push(this.url);
    }
  }

  const win = {
    location: { origin: ORIGIN, href: `${ORIGIN}${PREFIX}/` },
    fetch: (input: unknown) => {
      fetched.push(input instanceof URL ? input.href : String(input));
      return Promise.resolve('ok');
    },
    EventSource: FakeEventSource,
  } as unknown as FakeWindow;

  return { win, fetched, streamed };
}

/** Load the bridge fresh against a given basePath and window. */
async function install(basePath: string, win: FakeWindow) {
  vi.resetModules();
  process.env.NEXT_PUBLIC_BASE_PATH = basePath;
  (globalThis as Record<string, unknown>).window = win;
  await import('@/components/base-path-bridge');
}

const originalEnv = process.env.NEXT_PUBLIC_BASE_PATH;

beforeEach(() => {
  delete (globalThis as Record<string, unknown>).window;
});

afterEach(() => {
  delete (globalThis as Record<string, unknown>).window;
  if (originalEnv === undefined) delete process.env.NEXT_PUBLIC_BASE_PATH;
  else process.env.NEXT_PUBLIC_BASE_PATH = originalEnv;
});

describe('withBasePath / asset', () => {
  it('is a no-op with no basePath, and prefixes with one', async () => {
    vi.resetModules();
    process.env.NEXT_PUBLIC_BASE_PATH = '';
    const bare = await import('@/lib/base-path');
    expect(bare.asset('/brand-wordmark.png')).toBe('/brand-wordmark.png');

    vi.resetModules();
    process.env.NEXT_PUBLIC_BASE_PATH = PREFIX;
    const prefixed = await import('@/lib/base-path');
    expect(prefixed.asset('/brand-wordmark.png')).toBe(`${PREFIX}/brand-wordmark.png`);
  });

  it('is idempotent, and leaves anything that is not a root-absolute path alone', async () => {
    vi.resetModules();
    process.env.NEXT_PUBLIC_BASE_PATH = PREFIX;
    const { withBasePath } = await import('@/lib/base-path');

    // Applied twice — the fetch wrapper runs over paths a caller may already
    // have prefixed, and a second prefix would be silent and fatal.
    expect(withBasePath(withBasePath('/api/x'))).toBe(`${PREFIX}/api/x`);
    expect(withBasePath(PREFIX)).toBe(PREFIX);
    expect(withBasePath('api/x')).toBe('api/x');
    expect(withBasePath('https://elsewhere.example/api/x')).toBe('https://elsewhere.example/api/x');
  });
});

describe('the fetch wrapper', () => {
  it('prefixes the app\u2019s own /api calls', async () => {
    const { win, fetched } = makeWindow();
    await install(PREFIX, win);

    await win.fetch('/api/access-code/status');
    expect(fetched).toEqual([`${PREFIX}/api/access-code/status`]);
  });

  it('leaves alone what it does not own', async () => {
    const { win, fetched } = makeWindow();
    await install(PREFIX, win);

    await win.fetch('/health'); // not ours; some other app may serve it
    await win.fetch('api/relative'); // resolves against a page already prefixed
    await win.fetch('https://api.openai.com/v1/models'); // cross-origin
    await win.fetch(`${PREFIX}/api/already`); // prefixed by a caller

    expect(fetched).toEqual([
      '/health',
      'api/relative',
      'https://api.openai.com/v1/models',
      `${PREFIX}/api/already`,
    ]);
  });

  it('handles a URL object without disturbing a cross-origin one', async () => {
    const { win, fetched } = makeWindow();
    await install(PREFIX, win);

    await win.fetch(new URL(`${ORIGIN}/api/stages`));
    await win.fetch(new URL('https://elsewhere.example/api/stages'));

    expect(fetched).toEqual([
      `${ORIGIN}${PREFIX}/api/stages`,
      'https://elsewhere.example/api/stages',
    ]);
  });

  it('does not touch anything when the app owns its domain root', async () => {
    const { win, fetched } = makeWindow();
    const before = win.fetch;
    await install('', win);

    expect(win.fetch).toBe(before); // not even wrapped
    await win.fetch('/api/access-code/status');
    expect(fetched).toEqual(['/api/access-code/status']);
  });
});

describe('the EventSource wrapper', () => {
  it('prefixes a stream, which is what the workbench opens', async () => {
    const { win, streamed } = makeWindow();
    await install(PREFIX, win);

    new win.EventSource('/api/stages/intro/freshness');
    expect(streamed).toEqual([`${PREFIX}/api/stages/intro/freshness`]);
  });

  it('is left untouched when the app owns its domain root', async () => {
    const { win } = makeWindow();
    const before = win.EventSource;
    await install('', win);
    expect(win.EventSource).toBe(before);
  });
});
