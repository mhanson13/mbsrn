import { runBoundedBulkActionQueue, type BulkActionQueueProgress } from "./bulkActionQueue";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function flushMicrotasks(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("runBoundedBulkActionQueue", () => {
  it("respects concurrency cap and processes all items", async () => {
    const items = ["a", "b", "c", "d", "e", "f"];
    const deferredByItem = new Map<string, Deferred<string>>();
    let inFlight = 0;
    let maxInFlight = 0;
    const startedItems: string[] = [];

    const queuePromise = runBoundedBulkActionQueue({
      items,
      concurrency: 2,
      worker: async (item) => {
        const deferred = createDeferred<string>();
        deferredByItem.set(item, deferred);
        inFlight += 1;
        maxInFlight = Math.max(maxInFlight, inFlight);
        startedItems.push(item);
        try {
          return await deferred.promise;
        } finally {
          inFlight -= 1;
          deferredByItem.delete(item);
        }
      },
    });

    await flushMicrotasks();
    expect(startedItems).toEqual(["a", "b"]);
    expect(maxInFlight).toBe(2);

    deferredByItem.get("a")?.resolve("done-a");
    await flushMicrotasks();
    expect(startedItems).toEqual(["a", "b", "c"]);
    expect(maxInFlight).toBe(2);

    deferredByItem.get("b")?.resolve("done-b");
    await flushMicrotasks();
    expect(startedItems).toEqual(["a", "b", "c", "d"]);

    deferredByItem.get("c")?.resolve("done-c");
    deferredByItem.get("d")?.resolve("done-d");
    await flushMicrotasks();
    expect(startedItems).toEqual(["a", "b", "c", "d", "e", "f"]);

    deferredByItem.get("e")?.resolve("done-e");
    deferredByItem.get("f")?.resolve("done-f");
    const result = await queuePromise;

    expect(result.total).toBe(6);
    expect(result.succeeded).toBe(6);
    expect(result.failed).toBe(0);
    expect(result.successes).toHaveLength(6);
    expect(result.failures).toHaveLength(0);
    expect(maxInFlight).toBe(2);
  });

  it("accounts for failures and continues processing remaining items", async () => {
    const items = [1, 2, 3, 4, 5];
    const progressSnapshots: BulkActionQueueProgress[] = [];

    const result = await runBoundedBulkActionQueue({
      items,
      concurrency: 3,
      worker: async (item) => {
        if (item === 2 || item === 4) {
          throw new Error(`fail-${item}`);
        }
        return item * 10;
      },
      onProgress: (progress) => {
        progressSnapshots.push(progress);
      },
    });

    expect(result.total).toBe(5);
    expect(result.succeeded).toBe(3);
    expect(result.failed).toBe(2);
    expect(result.successes.map((entry) => entry.item).sort()).toEqual([1, 3, 5]);
    expect(result.failures.map((entry) => entry.item).sort()).toEqual([2, 4]);
    expect(progressSnapshots).toHaveLength(5);
    expect(progressSnapshots[0]?.processed).toBe(1);
    expect(progressSnapshots[4]).toEqual({
      total: 5,
      processed: 5,
      succeeded: 3,
      failed: 2,
    });
  });
});
