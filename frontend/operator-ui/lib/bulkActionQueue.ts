export type BulkActionQueueProgress = {
  total: number;
  processed: number;
  succeeded: number;
  failed: number;
};

export type BulkActionQueueSuccess<TItem, TResult> = {
  item: TItem;
  index: number;
  value: TResult;
};

export type BulkActionQueueFailure<TItem> = {
  item: TItem;
  index: number;
  error: unknown;
};

export type BulkActionQueueResult<TItem, TResult> = {
  total: number;
  succeeded: number;
  failed: number;
  successes: BulkActionQueueSuccess<TItem, TResult>[];
  failures: BulkActionQueueFailure<TItem>[];
};

type RunBoundedBulkActionQueueParams<TItem, TResult> = {
  items: TItem[];
  concurrency: number;
  worker: (item: TItem, index: number) => Promise<TResult>;
  onProgress?: (progress: BulkActionQueueProgress) => void;
};

function normalizeConcurrency(value: number): number {
  if (!Number.isFinite(value)) {
    return 1;
  }
  const parsed = Math.floor(value);
  if (parsed < 1) {
    return 1;
  }
  return parsed;
}

export async function runBoundedBulkActionQueue<TItem, TResult>(
  params: RunBoundedBulkActionQueueParams<TItem, TResult>,
): Promise<BulkActionQueueResult<TItem, TResult>> {
  const { items, worker, onProgress } = params;
  const total = items.length;
  if (total === 0) {
    return {
      total: 0,
      succeeded: 0,
      failed: 0,
      successes: [],
      failures: [],
    };
  }

  const concurrency = Math.min(normalizeConcurrency(params.concurrency), total);
  const successes: BulkActionQueueSuccess<TItem, TResult>[] = [];
  const failures: BulkActionQueueFailure<TItem>[] = [];
  const progress: BulkActionQueueProgress = {
    total,
    processed: 0,
    succeeded: 0,
    failed: 0,
  };
  let nextIndex = 0;

  const notifyProgress = () => {
    if (!onProgress) {
      return;
    }
    onProgress({
      total: progress.total,
      processed: progress.processed,
      succeeded: progress.succeeded,
      failed: progress.failed,
    });
  };

  const runWorker = async () => {
    while (true) {
      const currentIndex = nextIndex;
      nextIndex += 1;
      if (currentIndex >= total) {
        return;
      }

      const item = items[currentIndex];
      if (item === undefined) {
        progress.processed += 1;
        progress.failed += 1;
        failures.push({
          item: item as TItem,
          index: currentIndex,
          error: new Error("Bulk action queue item missing at index."),
        });
        notifyProgress();
        continue;
      }

      try {
        const value = await worker(item, currentIndex);
        successes.push({
          item,
          index: currentIndex,
          value,
        });
        progress.processed += 1;
        progress.succeeded += 1;
        notifyProgress();
      } catch (error) {
        failures.push({
          item,
          index: currentIndex,
          error,
        });
        progress.processed += 1;
        progress.failed += 1;
        notifyProgress();
      }
    }
  };

  await Promise.all(Array.from({ length: concurrency }, () => runWorker()));
  return {
    total,
    succeeded: successes.length,
    failed: failures.length,
    successes,
    failures,
  };
}
