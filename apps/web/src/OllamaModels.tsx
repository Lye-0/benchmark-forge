import { useEffect, useState } from 'react';
import { api } from './api';

export interface InstalledModel { name: string; revision: string | null; quantization: string | null; size_bytes: number | null }

export function OllamaModels({ endpoint, onSelect }: { endpoint: string; onSelect: (model: InstalledModel) => void }) {
  const [result, setResult] = useState<{ endpoint: string; models: InstalledModel[] } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    let active = true;
    setBusy(true); setError(''); setResult(null);
    const timer = setTimeout(() => {
      void api<{ models: InstalledModel[] }>('/ollama/models', { endpoint })
        .then(data => { if (active) setResult({ endpoint, models: data.models }); })
        .catch(e => { if (active) setError((e as Error).message); })
        .finally(() => { if (active) setBusy(false); });
    }, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [endpoint, epoch]);
  const models = result?.endpoint === endpoint ? result.models : [];
  return <div className="ollama-models"><label className="field">インストール済みモデルから入力<select value="" disabled={busy || !models.length} onChange={event => { const selected = models.find(m => m.name === event.target.value); if (selected) onSelect(selected); }}><option value="">{busy ? 'Ollamaから取得中…' : models.length ? 'モデルを選ぶと登録項目に反映します' : '候補なし（手入力できます）'}</option>{models.map(model => <option key={model.name} value={model.name}>{model.name}{model.quantization ? ` · ${model.quantization}` : ''}{model.size_bytes !== null ? ` · ${(model.size_bytes / 1024 ** 3).toFixed(1)} GiB` : ''}</option>)}</select></label><button type="button" className="secondary" disabled={busy} onClick={() => setEpoch(value => value + 1)}>候補を再取得</button>{error && <p role="status">{error}</p>}{!busy && result?.endpoint === endpoint && !models.length && <p role="status">このOllamaにインストール済みモデルはありません。</p>}</div>;
}
