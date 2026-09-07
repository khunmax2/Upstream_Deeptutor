/**
 * Give `ReadableStream` async iteration where the engine has none.
 *
 * WebKit has never shipped `ReadableStream.prototype[Symbol.asyncIterator]`,
 * and pdf.js reads a page's text through it:
 *
 * ```js
 * async getTextContent(params) {
 *   const stream = this.streamTextContent(params);
 *   for await (const chunk of stream) { … }   // TypeError in Safari
 * }
 * ```
 *
 * The failure is a bare `TypeError: undefined is not a function`, thrown deep
 * inside the library, so in the reader it surfaced as *nothing at all*: the
 * canvas painted, the page looked right, and the text layer — the surface the
 * whole selection/highlight/ask flow stands on — was silently empty on every
 * page. Verified against Safari 26.6.2 (`AppleWebKit/605.1.15`), where
 * `getTextContent()` on a nine-page PDF threw, and returned 113 items with the
 * shim installed.
 *
 * Implements the WHATWG `ReadableStream.values()` contract, which is what
 * `Symbol.asyncIterator` aliases: `return()` cancels the stream unless
 * `preventCancel` was asked for, and the lock is released on every exit path so
 * the stream stays reusable after a `break` or a throw.
 *
 * Feature-detected, so engines that have it keep their native implementation.
 */

type StreamIterator<T> = AsyncIterableIterator<T> & {
  next(): Promise<IteratorResult<T>>;
};

export function installReadableStreamAsyncIterator(): void {
  if (typeof ReadableStream === "undefined") return;
  if (Symbol.asyncIterator in ReadableStream.prototype) return;

  function values<T>(
    this: ReadableStream<T>,
    options?: { preventCancel?: boolean },
  ): StreamIterator<T> {
    const preventCancel = options?.preventCancel === true;
    const reader = this.getReader();
    const iterator: StreamIterator<T> = {
      async next() {
        try {
          const result = await reader.read();
          // Releasing on the final chunk — not only on return() — matters for
          // pdf.js, which drains a text stream to completion and never calls
          // return(): a retained lock would fail the next read of the page.
          if (result.done) reader.releaseLock();
          return result as IteratorResult<T>;
        } catch (error) {
          reader.releaseLock();
          throw error;
        }
      },
      async return(value?: unknown) {
        if (preventCancel) {
          reader.releaseLock();
        } else {
          const cancelled = reader.cancel(value);
          reader.releaseLock();
          await cancelled;
        }
        return { done: true, value } as IteratorResult<T>;
      },
      [Symbol.asyncIterator]() {
        return iterator;
      },
    };
    return iterator;
  }

  const descriptor: PropertyDescriptor = {
    value: values,
    writable: true,
    enumerable: false,
    configurable: true,
  };
  Object.defineProperty(ReadableStream.prototype, "values", descriptor);
  Object.defineProperty(ReadableStream.prototype, Symbol.asyncIterator, descriptor);
}
