import { OllamaModels, type InstalledModel } from './OllamaModels';
import { DeleteButton } from './DeleteButton';
import { useMounted } from './useMounted';
import { useEffect, useRef, useState } from 'react';
import { Cpu, Plug, Plus, X } from 'lucide-react';
import { api } from './api';
import type { Model } from './types';

export function ModelManager({ models, refresh, onError }: { models: Model[]; refresh: () => Promise<void>; onError: (text: string) => void }) {
  const mounted = useMounted();
  const [editing, setEditing] = useState<Model | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const checkGeneration = useRef(0);
  const [checking, setChecking] = useState<Record<string, boolean>>({});
  const [checks, setChecks] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!editing) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.current?.showModal();
    return () => { document.body.style.overflow = previousOverflow; };
  }, [editing]);
  const closeEditor = () => { dialog.current?.close(); setEditing(null); };
  const saving = (value: boolean) => { setBusy(value); if (value) { checkGeneration.current += 1; setChecks({}); } };
  const check = async (model: Model) => {
    if (checking[model.model_id]) return;
    const generation = checkGeneration.current;
    setChecking(old => ({ ...old, [model.model_id]: true }));
    setChecks(old => ({ ...old, [model.model_id]: '' }));
    try { const result = await api<{ reason: string; status: string }>(`/models/${model.model_id}/check`, {}); if (generation === checkGeneration.current) setChecks(old => ({ ...old, [model.model_id]: `${result.status}: ${result.reason}` })); }
    catch (e) { mounted.current && generation === checkGeneration.current && onError((e as Error).message); }
    finally { setChecking(old => ({ ...old, [model.model_id]: false })); }
  };
  return <><div className="page-heading"><div><div className="eyebrow">MODEL WORKSPACE</div><h1>モデル</h1><p>バックエンドと推論条件を登録。対応機能と接続検証を分けて管理します。</p></div><span className="badge">{models.length} models</span></div><div className="models-grid"><div>{models.map(model => <section className="panel model-card" key={model.model_id}><div className="panel-title"><div className="model-card-title"><span className="model-icon"><Cpu size={20}/></span><div><h2>{model.name}</h2><p>{model.backend} · {model.model}</p></div></div><span className={`badge ${model.capabilities.test_only ? 'preview' : ''}`}>{model.capabilities.status}</span></div><dl><div><dt>リビジョン / 量子化</dt><dd>{model.revision} / {model.quantization}</dd></div><div><dt>対応機能</dt><dd>{model.capabilities.native_tools ? 'テキスト / ネイティブツール（Mockまたは申告）' : 'テキストのみ'}</dd></div><div><dt>温度 / 最大出力</dt><dd>{model.temperature} / {model.max_tokens} tokens</dd></div></dl><p className="fine-print">{model.capabilities.reason}</p><div className="button-row model-actions"><button className="secondary" disabled={busy} onClick={() => setEditing(model)}>設定を編集</button><button className="secondary" disabled={busy || checking[model.model_id]} onClick={() => void check(model)}><Plug size={15}/> {checking[model.model_id] ? '確認中…' : model.backend === 'ollama' ? 'Ollama接続を確認' : '対応機能を確認'}</button><DeleteButton path={`/models/${model.model_id}/delete`} title={`「${model.name}」の登録を削除しますか？`} description="このアプリへの登録設定を削除します。モデル本体のファイルと、過去・実行中の評価結果は残ります。" onDeleted={refresh}/></div>{checks[model.model_id] && <p role="status" className="connection-message">{checks[model.model_id]}</p>}</section>)}</div><section className="panel register-panel"><div className="panel-title"><h2><Plus size={18}/> モデルを登録</h2></div><ModelForm models={models} refresh={refresh} onError={onError} onSaving={saving}/></section></div>
    {editing && <dialog ref={dialog} className="model-dialog" aria-labelledby="model-edit-title" onCancel={event => { event.preventDefault(); if (!busy) closeEditor(); }}>
      <div className="panel-title"><h2 id="model-edit-title">モデル設定を編集</h2><button type="button" className="icon-button" aria-label="編集を閉じる" disabled={busy} onClick={closeEditor}><X size={20}/></button></div>
      <ModelForm key={editing.model_id} model={editing} models={models} refresh={refresh} onError={onError} onSaving={saving} onSaved={closeEditor} onCancel={closeEditor}/>
    </dialog>}
  </>;
}

function ModelForm({ model, models, refresh, onError, onSaving, onSaved, onCancel }: { model?: Model; models: Model[]; refresh: () => Promise<void>; onError: (text: string) => void; onSaving: (busy: boolean) => void; onSaved?: () => void; onCancel?: () => void }) {
  const mounted = useMounted();
  const defaults = { model_id: '', name: '', backend: 'ollama', model: '', endpoint: 'http://127.0.0.1:11434', revision: 'unrecorded', quantization: 'N/A', temperature: 0, max_tokens: 512, timeout_seconds: 30, context_length: '' as number | '', device: 'cpu', native_tools: false, streaming: false, gpu_sampling: false, inference_seed: 0, mock_behavior: 'reference' };
  const [form, setForm] = useState(() => { if (!model) return defaults; const { capabilities: _capabilities, ...config } = model; return { ...defaults, ...config, context_length: config.context_length ?? '' }; });
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const autoFields = useRef({ id: '', name: '' });
  const selectInstalled = (selected: InstalledModel) => {
    const base = `ollama-${selected.name.replace(/[^A-Za-z0-9_.-]+/g, '-').slice(0, 60)}`;
    let id = base;
    for (let suffix = 2; models.some(item => item.model_id === id); suffix += 1) id = `${base}-${suffix}`;
    const name = selected.name.slice(0, 100);
    const previous = autoFields.current;
    setForm(old => ({ ...old, model: selected.name, revision: selected.revision ?? 'unrecorded', quantization: selected.quantization ?? 'N/A',
      model_id: !model && (!old.model_id || old.model_id === previous.id) ? id : old.model_id,
      name: !model && (!old.name || old.name === previous.name) ? name : old.name,
      ...(old.model !== selected.name ? { native_tools: false, context_length: '' as const } : {}),
    }));
    autoFields.current = { id, name };
    setSaved(false);
  };
  const existing = models.find(item => item.model_id === form.model_id);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); if (busy || (existing && model?.model_id !== form.model_id)) return;
    setBusy(true); onSaving(true); setSaved(false); setError('');
    try {
      await api('/models', { ...form, endpoint: form.backend === 'ollama' ? form.endpoint : 'http://127.0.0.1:11434', context_length: form.context_length === '' ? null : form.context_length });
      await refresh();
      if (mounted.current) { setSaved(true); onSaved?.(); }
    } catch (e) { if (mounted.current) { setError((e as Error).message); if (!model) onError((e as Error).message); } }
    finally { setBusy(false); onSaving(false); }
  };
  return <><form onChange={() => setSaved(false)} onSubmit={e => void submit(e)}><fieldset disabled={busy} className="form-fields"><label className="field">モデルID<input disabled={!!model} required pattern="[A-Za-z0-9_.-]+" maxLength={80} value={form.model_id} onChange={e => setForm({ ...form, model_id: e.target.value })} placeholder="例：ollama-llama32"/></label><label className="field">表示名<input required maxLength={100} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Llama 3.2 / ローカル"/></label><label className="field">バックエンド<select value={form.backend} onChange={e => setForm({ ...form, backend: e.target.value })}><option value="ollama">Ollama</option><option value="mock">Mock（診断専用）</option><option value="transformers">Transformers（ローカルモデル専用）</option><option value="codex-cli">Codex CLI（安全性未検証・実行不可）</option><option value="codex-app-server">Codex App Server（安全性未検証・実行不可）</option></select></label>{form.backend === 'ollama' && <OllamaModels endpoint={form.endpoint} onSelect={selectInstalled}/>}<label className="field">{form.backend === 'transformers' ? 'モデルの保存フォルダ（絶対パス）' : form.backend === 'ollama' ? 'Ollamaのモデル名（タグを含む）' : 'モデル識別子'}<input required maxLength={200} value={form.model} onChange={e => setForm({ ...form, model: e.target.value })}/></label>{form.backend === 'ollama' && <label className="field">Ollama接続先<input required value={form.endpoint} onChange={e => setForm({ ...form, endpoint: e.target.value })}/><small>127.0.0.1 または ::1 のHTTPのみ。</small></label>}<div className="form-grid"><label className="field">リビジョン<input value={form.revision} onChange={e => setForm({ ...form, revision: e.target.value })}/></label><label className="field">量子化<input value={form.quantization} onChange={e => setForm({ ...form, quantization: e.target.value })}/></label><label className="field">コンテキスト上限<input type="number" min={1} max={10000000} value={form.context_length} onChange={e => setForm({ ...form, context_length: e.target.value === '' ? '' : Number(e.target.value) })}/><small>空欄はバックエンドの既定値。</small></label>{form.backend === 'transformers' && <label className="field">推論デバイス<select value={form.device} onChange={e => setForm({ ...form, device: e.target.value })}><option value="cpu">CPU</option><option value="cuda">CUDA GPU</option></select><small>取得済みモデルのディレクトリを指定。safetensorsのみ・問題ごとにロード。</small></label>}{form.backend === 'ollama' && <label className="field"><span><input type="checkbox" checked={form.native_tools} onChange={e => setForm({ ...form, native_tools: e.target.checked })}/>モデルのネイティブツール対応を申告</span><small>バックエンド対応だけではモデルの対応を保証しません。実接続は未検証です。</small></label>}{form.backend === 'ollama' && <label className="field"><span><input type="checkbox" checked={form.streaming} onChange={e => setForm({ ...form, streaming: e.target.checked })}/>ストリーミングで初回応答時間を測る</span><small>最初の可視テキストの受信時刻を測定します。ツール評価は非ストリーミングです。</small></label>}<label className="field"><span><input type="checkbox" checked={form.gpu_sampling} onChange={e => setForm({ ...form, gpu_sampling: e.target.checked })}/>評価中のGPU使用状況を計測</span><small>任意。約1秒間隔でホストGPU全体を計測します。他アプリの負荷も含み、取得できなくても評価を続けます。計測の有無で速度条件が変わります。</small></label><label className="field">推論シード<input type="number" min={0} max={4294967295} value={form.inference_seed} onChange={e => setForm({ ...form, inference_seed: Number(e.target.value) })}/><small>問題生成用シードとは独立です。バックエンドやGPUの違いによる完全一致は保証しません。</small></label><label className="field">温度<input type="number" min={0} max={2} step="0.1" value={form.temperature} onChange={e => setForm({ ...form, temperature: Number(e.target.value) })}/></label><label className="field">最大出力トークン<input type="number" min={1} max={32768} value={form.max_tokens} onChange={e => setForm({ ...form, max_tokens: Number(e.target.value) })}/></label><label className="field">タイムアウト（秒）<input type="number" min={.1} max={600} step="0.1" value={form.timeout_seconds} onChange={e => setForm({ ...form, timeout_seconds: Number(e.target.value) })}/></label></div>{error && <p role="alert" className="error-banner">{error}</p>}<div className="button-row">{onCancel && <button type="button" className="secondary" disabled={busy} onClick={onCancel}>キャンセル</button>}<button type="submit" className={model ? "primary" : "primary full-width"} disabled={busy || (!!existing && model?.model_id !== form.model_id)}>{busy ? '保存中…' : existing ? model?.model_id === form.model_id ? `「${existing.name}」の設定を更新` : '登録済みIDです：モデル一覧の「設定を編集」を選択'  : '新しいモデルを登録'}</button></div>{saved && <p role="status" className="connection-message">モデルを保存しました。</p>}</fieldset></form><p className="fine-print">モデル一覧や接続確認だけでは推論権限・実モデル性能は確認できません。認証情報をこのフォームに入力しないでください。</p></>;
}
