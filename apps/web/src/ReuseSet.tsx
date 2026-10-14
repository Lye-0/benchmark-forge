import { useState } from 'react';
import { api } from './api';
import type { Model, Run } from './types';

export function ReuseSet({ runs, models, onCreated, onError }: { runs: Run[]; models: Model[]; onCreated: (id: string) => void; onError: (message: string) => void }) {
  const [source, setSource] = useState('');
  const [model, setModel] = useState('');
  const [busy, setBusy] = useState(false);
  const candidates = runs.filter(run => (run.measurement_kind ?? 'text') === 'text');
  const selected = candidates.find(run => run.id === source);
  const available = models.some(m => m.model_id === model && m.capabilities.available);
  const start = async () => {
    if (!selected || !available) return;
    setBusy(true);
    try {
      const result = await api<{ run_ids: string[] }>('/runs', { set_id: selected.set_id, model_ids: [model] });
      onCreated(result.run_ids[0]);
    } catch (error) { onError((error as Error).message); }
    finally { setBusy(false); }
  };
  return <section className="panel"><h2>保存済みセットで追加評価</h2>
    <p>以前と同じ問題を、選んだモデルだけで実行します。問題を再生成せず、既存の結果も保持します。</p>
    <div className="form-grid">
      <label className="field">元の実行<select aria-label="元の実行" value={source} disabled={busy} onChange={event => setSource(event.target.value)}><option value="">選択してください</option>{candidates.map(run => <option key={run.id} value={run.id}>{run.model.name} · {run.total}問 · {run.id}</option>)}</select></label>
      <label className="field">追加評価モデル<select aria-label="追加評価モデル" value={model} disabled={busy} onChange={event => setModel(event.target.value)}><option value="">選択してください</option>{models.map(m => <option key={m.model_id} value={m.model_id} disabled={!m.capabilities.available}>{m.name}</option>)}</select></label>
    </div>
    {selected && <p className="fine-print">セット: {selected.set_hash} · {selected.total}問</p>}
    <button className="secondary" disabled={busy || !selected || !available} onClick={() => void start()}>{busy ? '開始中…' : '保存済みセットで実行'}</button>
  </section>;
}
