export interface RunProgress { id: string; status: string; completed: number; total: number; revision: number }

// A sequential queue may advance a different selected model while the resumed
// model waits. Detect a stalled queue separately from total execution duration.
export class ProgressWatch {
  private signature = '';
  private changedAt: number;
  constructor(private ids: string[], private startedAt: number, private stallMs = 15000, private deadlineMs = 120000) {
    this.changedAt = startedAt;
  }
  check(now: number): void {
    if (now - this.startedAt >= this.deadlineMs) throw new Error('Run deadline exceeded');
    if (now - this.changedAt >= this.stallMs) throw new Error('Run queue stopped making progress (or progress endpoint unavailable)');
  }
  observe(rows: RunProgress[], now: number): boolean {
    const selected = this.ids.map(id => {
      const row = rows.find(r => r.id === id);
      if (!row) throw new Error(`Run missing: ${id}`);
      return row;
    });
    const detail = JSON.stringify(selected);
    if (selected.some(r => !['queued', 'running', 'completed'].includes(r.status))) {
      throw new Error(`Unexpected run state after resume: ${detail}`);
    }
    if (now - this.startedAt >= this.deadlineMs) throw new Error(`Run deadline exceeded: ${detail}`);
    if (selected.every(r => r.status === 'completed' && r.completed === r.total)) return true;
    const signature = JSON.stringify(selected.map(r => [r.id, r.status, r.completed]));
    if (signature !== this.signature) { this.signature = signature; this.changedAt = now; }
    if (now - this.changedAt >= this.stallMs) throw new Error(`Run queue stopped making progress: ${detail}`);
    return false;
  }
}


// Retry only a transport timeout. HTTP errors, invalid payloads and stalled
// runs remain failures; failed reads never reset the progress/deadline clocks.
export async function waitForRuns(
  watch: ProgressWatch,
  fetchRows: () => Promise<RunProgress[]>,
  now = Date.now,
  sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms)),
): Promise<void> {
  for (;;) {
    watch.check(now());
    let rows: RunProgress[];
    try { rows = await fetchRows(); }
    catch (error) {
      if (!(error instanceof Error) || !(error.name === 'TimeoutError' || /^apiRequestContext\.get: Timeout \d+ms exceeded/.test(error.message))) throw error;
      watch.check(now());
      await sleep(1000);
      continue;
    }
    watch.check(now());
    if (watch.observe(rows, now())) return;
    await sleep(1000);
  }
}
