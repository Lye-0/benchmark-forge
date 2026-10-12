import { useState } from 'react';
import { api } from './api';
import type { Model } from './types';

export function SpeedProbe({ models, onCreated, onError }: { models: Model[]; onCreated: (id: string) => void; onError: (value: string) => void }) {
  const [model, setModel] = useState('mock-reference');
  const [input, setInput] = useState(100);
  const [output, setOutput] = useState(32);
  const [busy, setBusy] = useState(false);
  const start = async () => {
    setBusy(true);
    try {
      const frozen = await api<{ set_id: string }>('/speed-probes', { input_repetitions: input, output_repetitions: output, repetitions: 3 });
      const result = await api<{ run_ids: string[] }>('/runs', { set_id: frozen.set_id, model_ids: [model] });
      onCreated(result.run_ids[0]);
    } catch (e) { onError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <section className="panel"><h2>専用速度試験</h2><p>固定した入力文と要求出力で3回測定します。トークン数はモデルのtokenizerで異なります。要求長未達の結果を同一長の速度として比較しないでください。</p><div className="form-grid"><label className="field">速度試験モデル<select value={model} onChange={e => setModel(e.target.value)}>{models.map(m => <option key={m.model_id} value={m.model_id} disabled={!m.capabilities.available}>{m.name}</option>)}</select></label><label className="field">入力sampleの反復数<input type="number" min={1} max={2000} value={input} onChange={e => setInput(Number(e.target.value))}/></label><label className="field">出力xの要求個数<input type="number" min={1} max={512} value={output} onChange={e => setOutput(Number(e.target.value))}/></label></div><button className="secondary" disabled={busy} onClick={() => void start()}>速度試験を開始</button></section>;
}
