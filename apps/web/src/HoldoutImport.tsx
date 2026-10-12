import { useState } from 'react';
import { api } from './api';
import type { Model } from './types';

export function HoldoutImport({ models, onCreated, onError }: { models: Model[]; onCreated: (id: string) => void; onError: (message: string) => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [frozen, setFrozen] = useState<{ set_id: string; set_hash: string; count: number; warnings: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const upload = async (file: File) => {
    setFrozen(null); setBusy(true);
    try {
      if (file.size > 900000) throw new Error('ファイルは900KB以下にしてください');
      const result = await api<{ set_id: string; set_hash: string; count: number; warnings: string[] }>('/holdouts', { jsonl: await file.text() });
      setFrozen(result);
    } catch (e) { onError((e as Error).message); }
    finally { setBusy(false); }
  };
  const start = async () => {
    setBusy(true);
    try { const result = await api<{ run_ids: string[] }>('/runs', { set_id: frozen?.set_id, model_ids: selected }); onCreated(result.run_ids[0]); }
    catch (e) { onError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <section className="panel"><h2>私有holdoutの取り込み</h2><p>JSONLの先頭にschema: forge-holdout-v1、name、source、licenseを含むメタデータを置き、以降にprompt、category_id、target_difficulty、answer_specを持つ問題を記載します。</p><p className="fine-print">ローカルDBに保存します。解答内容や利用権の検証は取り込み元で行ってください。結果のエクスポートには私有問題と参照解答が含まれます。</p><label className="field">私有問題JSONL<input type="file" accept=".jsonl" disabled={busy} onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file); }}/></label>{frozen && <><p role="status">{frozen.count}問を取り込みました。</p><code className="hash">{frozen.set_hash}</code>{frozen.warnings.map(w => <p className="fine-print" key={w}>{w}</p>)}<fieldset><legend>同じセットで評価するモデル</legend>{models.map(m => <label className="field" key={m.model_id}><span><input type="checkbox" disabled={!m.capabilities.available} checked={selected.includes(m.model_id)} onChange={e => setSelected(old => e.target.checked ? [...old, m.model_id] : old.filter(id => id !== m.model_id))}/>{m.name}</span></label>)}</fieldset><button className="primary" disabled={busy || !selected.length} onClick={() => void start()}>取り込んだセットで実行</button></>}</section>;
}
