import { useMounted } from './useMounted';
import { useState } from 'react';
import { api } from './api';
import type { Model } from './types';

export function SpeedProbe({ models, onCreated, onError }: { models: Model[]; onCreated: (id: string) => void; onError: (value: string) => void }) {
  const mounted = useMounted();
  const [model, setModel] = useState(() => models.some(m => m.model_id === 'mock-reference' && m.capabilities.available) ? 'mock-reference' : '');
  const [input, setInput] = useState(100);
  const [output, setOutput] = useState(32);
  const [busy, setBusy] = useState(false);
  const valid = Number.isInteger(input) && input >= 1 && input <= 2000 && Number.isInteger(output) && output >= 1 && output <= 512 && models.some(m => m.model_id === model && m.capabilities.available);
  const start = async () => {
    if (!valid) return;
    setBusy(true);
    try {
      const frozen = await api<{ set_id: string }>('/speed-probes', { input_repetitions: input, output_repetitions: output, repetitions: 3 });
      const result = await api<{ run_ids: string[] }>('/runs', { set_id: frozen.set_id, model_ids: [model] });
      if (mounted.current) onCreated(result.run_ids[0]);
    } catch (e) { mounted.current && onError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <section className="panel"><h2>専用速度試験</h2><p>固定した入力文と要求出力で3回測定します。トークン数はモデルのtokenizerで異なります。要求長未達の結果を同一長の速度として比較しないでください。</p><div className="form-grid"><label className="field">速度試験モデル<select disabled={busy} value={model} onChange={e => setModel(e.target.value)}><option value="">モデルを選択してください</option>{models.map(m => <option key={m.model_id} value={m.model_id} disabled={!m.capabilities.available}>{m.name}</option>)}</select></label><label className="field">入力語「sample」の反復数<input type="number" disabled={busy} min={1} max={2000} value={input} onChange={e => setInput(Number(e.target.value))}/></label><label className="field">出力文字「x」の要求個数<input type="number" disabled={busy} min={1} max={512} value={output} onChange={e => setOutput(Number(e.target.value))}/></label></div><button className="secondary" disabled={busy || !valid} onClick={() => void start()}>{busy ? '開始中…' : '速度試験を開始（3回）'}</button></section>;
}
