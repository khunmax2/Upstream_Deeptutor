import assert from "node:assert/strict";
import test from "node:test";

import { installReadableStreamAsyncIterator } from "../lib/readable-stream-async-iterator";

/**
 * WebKit ships no `ReadableStream.prototype[Symbol.asyncIterator]`, and pdf.js
 * reads page text with `for await (const chunk of stream)`. Node has the real
 * thing, so these tests run against a stand-in prototype that is missing it —
 * the shape Safari presents.
 */
function withoutAsyncIteration<T>(run: () => T): T {
  const proto = ReadableStream.prototype as unknown as Record<
    string | symbol,
    unknown
  >;
  const iterator = Object.getOwnPropertyDescriptor(proto, Symbol.asyncIterator);
  const values = Object.getOwnPropertyDescriptor(proto, "values");
  delete proto[Symbol.asyncIterator];
  delete proto.values;
  try {
    return run();
  } finally {
    if (iterator) Object.defineProperty(proto, Symbol.asyncIterator, iterator);
    if (values) Object.defineProperty(proto, "values", values);
    else delete proto.values;
  }
}

/** The lib.dom types omit the very method this shim adds, so casting is the point. */
function iterable<T>(stream: ReadableStream<T>): AsyncIterable<T> {
  return stream as unknown as AsyncIterable<T>;
}

function streamOf<T>(chunks: T[]): ReadableStream<T> {
  return new ReadableStream<T>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

test("a stream with no async iteration gains one", async () => {
  await withoutAsyncIteration(async () => {
    assert.equal(Symbol.asyncIterator in ReadableStream.prototype, false);
    installReadableStreamAsyncIterator();

    const seen: number[] = [];
    for await (const chunk of iterable(streamOf([1, 2, 3]))) seen.push(chunk);

    assert.deepEqual(seen, [1, 2, 3]);
  });
});

test("draining to completion releases the lock", async () => {
  await withoutAsyncIteration(async () => {
    installReadableStreamAsyncIterator();
    const stream = streamOf(["a", "b"]);

    for await (const _chunk of iterable(stream)) void _chunk;

    // pdf.js drains a text stream and never calls return(); a lock retained
    // past the final chunk would fail the next read of that page.
    assert.equal(stream.locked, false);
  });
});

test("breaking out of the loop cancels the stream and unlocks it", async () => {
  await withoutAsyncIteration(async () => {
    installReadableStreamAsyncIterator();
    let cancelled = false;
    const stream = new ReadableStream<number>({
      start(controller) {
        controller.enqueue(1);
        controller.enqueue(2);
      },
      cancel() {
        cancelled = true;
      },
    });

    for await (const chunk of iterable(stream)) {
      assert.equal(chunk, 1);
      break;
    }

    assert.equal(cancelled, true);
    assert.equal(stream.locked, false);
  });
});

test("a stream error unlocks rather than stranding the reader", async () => {
  await withoutAsyncIteration(async () => {
    installReadableStreamAsyncIterator();
    const stream = new ReadableStream<number>({
      start(controller) {
        controller.error(new Error("boom"));
      },
    });

    await assert.rejects(async () => {
      for await (const _chunk of iterable(stream)) void _chunk;
    }, /boom/);
    assert.equal(stream.locked, false);
  });
});

test("an engine that already has async iteration keeps its own", async () => {
  const before = Object.getOwnPropertyDescriptor(
    ReadableStream.prototype,
    Symbol.asyncIterator,
  );

  installReadableStreamAsyncIterator();

  assert.deepEqual(
    Object.getOwnPropertyDescriptor(
      ReadableStream.prototype,
      Symbol.asyncIterator,
    ),
    before,
  );
});
