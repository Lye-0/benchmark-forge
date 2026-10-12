export interface RunProgress { id: string; status: string; completed: number; total: number; revision: number }

// A sequential queue may advance a different selected model while the resumed
// model waits. Detect a stalled queue separately from total execution duration.
export class ProgressWatch {
  private signature = '';
  private changedAt: number;
  constructor(private ids: string[], private startedAt: number, private stallMs = 15000, private deadlineMs = 120000) {
    this.changedAt = startedAt;
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
