import { useMounted } from './useMounted';
import { GenerationQualityPanel } from './GenerationQualityPanel';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, Fingerprint, Play, Save } from 'lucide-react';
import { api } from './api';
import { allGenerators, CategoryTree } from './CategoryTree';
import type { Config, Frozen, Model, Preset, Registry } from './types';

export function NewBenchmark({ registry, models, presets, onCreated, refresh, onError }: { registry: Registry; models: Model[]; presets: Preset[]; onCreated: (ids: string[]) => void; refresh: () => Promise<void>; onError: (text: string) => void }) {
  const mounted = useMounted();
  const initial = presets.find(p => p.id === 'preview-quick-v1')!;
  const [config, setConfig] = useState<Config>({ ...initial.config });
  const [selectedModels, setSelectedModels] = useState(() => models.filter(m => m.model_id === 'mock-reference' && m.capabilities.available).map(m => m.model_id));
  const [frozen, setFrozen] = useState<Frozen | null>(null);
  const [busy, setBusy] = useState(false);
  const [presetName, setPresetName] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [presetId, setPresetId] = useState(initial.id);
  useEffect(() => { setSelectedModels(old => old.filter(id => models.some(m => m.model_id === id && m.capabilities.available))); }, [models]);
  const configRevision = useRef(0);
  const change = (patch: Partial<Config>) => { configRevision.current += 1; setConfig(old => ({ ...old, ...patch, custom: true })); setFrozen(null); setSaved(false); };
  const apply = (id: string) => { const p = presets.find(p => p.id === id); if (p) { configRevision.current += 1; setConfig({ ...p.config }); setPresetId(id); setFrozen(null); setSaved(false); } };
  useEffect(() => { setFrozen(null); }, [config]);
  const coverage = new Set(allGenerators(registry.categories).filter(g => config.generator_ids.includes(g.id)).map(g => g.category_id)).size;
  const fixedCount = Math.floor(config.count * config.fixed_ratio + .5);
  const validation = !config.generator_ids.length ? '生成器を選択してください。'
    : !Number.isInteger(config.count) || config.count < Math.max(1, config.generator_ids.length) || config.count > 8000 ? `問題数は${Math.max(1, config.generator_ids.length)}〜8000の整数で入力してください。`
    : !Number.isInteger(config.seed) || config.seed < 0 || config.seed > 4294967295 ? 'シードは0〜4294967295の整数で入力してください。'
    : !Number.isFinite(config.difficulty_min) || !Number.isFinite(config.difficulty_max) || config.difficulty_min < 0 || config.difficulty_max > 100 || config.difficulty_min > config.difficulty_max ? '難易度は0〜100で、下限が上限以下になるよう入力してください。'
    : !selectedModels.length ? '評価するモデルを選択してください。' : selectedModels.length > 10 ? 'モデルは10件まで選択できます。' : '';
  const valid = !validation;
  const freeze = async () => {
    setBusy(true); onError('');
    const revision = configRevision.current;
    try { const result = await api<Frozen>('/sets', config); if (revision === configRevision.current) setFrozen(result); } catch (e) { mounted.current && onError((e as Error).message); }
    finally { setBusy(false); }
  };
  const start = async () => {
    if (!frozen) return;
    setBusy(true);
    try { const response = await api<{ run_ids: string[] }>('/runs', { set_id: frozen.set_id, model_ids: selectedModels }); await refresh(); if (mounted.current) onCreated(response.run_ids); }
    catch (e) { mounted.current && onError((e as Error).message); }
    finally { setBusy(false); }
  };
  const save = async () => {
    if (!presetName.trim() || saving) return;
    setSaving(true);
    const revision = configRevision.current;
    try { await api('/presets', { name: presetName, config }); if (revision === configRevision.current) setSaved(true); await refresh(); }
    catch (e) { mounted.current && onError((e as Error).message); }
    finally { setSaving(false); }
  };
  return <>
    <div className="page-heading"><div><div className="eyebrow">NEW BENCHMARK</div><h1>新しいベンチマーク</h1><p>評価条件を揃え、問題セットを確定してから実行します。</p></div><span className="badge preview">Preview v1</span></div>
    <div className="setup-grid"><div className="setup-main">
      <section className="panel"><div className="panel-title"><h2><span className="step-number">01</span> 評価プリセット</h2>{config.custom && <span className="badge custom">変更したカスタム</span>}</div><div className="preset-grid">{presets.filter(p => !p.id.startsWith('user-')).map(p => <button key={p.id} className={`preset ${presetId === p.id ? 'selected' : ''}`} onClick={() => apply(p.id)}><strong>{p.name}</strong><small>{p.description}</small></button>)}</div>{presets.some(p => p.id.startsWith('user-')) && <label className="field">保存したプリセット<select value={presetId.startsWith('user-') ? presetId : ''} onChange={e => apply(e.target.value)}><option value="" disabled>選択してください</option>{presets.filter(p => p.id.startsWith('user-')).map(p => <option value={p.id} key={p.id}>{p.name}</option>)}</select></label>}</section>
      <section className="panel"><div className="panel-title"><h2><span className="step-number">02</span> 評価するモデル</h2><span className="muted">{selectedModels.length} / 10モデル · 順次実行</span></div><div className="model-choices">{models.map(model => <label className={`model-choice ${selectedModels.includes(model.model_id) ? 'selected' : ''}`} key={model.model_id}><input type="checkbox" disabled={!model.capabilities.available || (selectedModels.length >= 10 && !selectedModels.includes(model.model_id))} checked={selectedModels.includes(model.model_id)} onChange={e => setSelectedModels(e.target.checked ? [...selectedModels, model.model_id] : selectedModels.filter(id => id !== model.model_id))}/><span><strong>{model.name}</strong><small>{model.capabilities.reason}</small></span><span className="badge">{model.backend}</span></label>)}</div><p className="fine-print">Mockは動作診断専用です。複数モデルには、同じ確定済み問題セットを使用します。</p></section>
      <section className="panel"><div className="panel-title"><h2><span className="step-number">03</span> カテゴリと生成器</h2><span className="muted">{coverage} / 16 カテゴリ</span></div><CategoryTree categories={registry.categories} selected={config.generator_ids} onChange={ids => change({ generator_ids: ids })}/></section>
      <section className="panel"><div className="panel-title"><h2><span className="step-number">04</span> 問題の配分</h2></div><div className="form-grid"><label className="field">問題数<input aria-label="問題数" type="number" min={config.generator_ids.length || 1} max={8000} value={config.count} onChange={e => change({ count: Number(e.target.value) })}/><small>選択した生成器に最低1問ずつ割り当てます。</small></label><label className="field">シード<input type="number" min={0} max={4294967295} value={config.seed} onChange={e => change({ seed: Number(e.target.value) })}/><small>同じ版・設定で同じセットを再現。</small></label><label className="field">難易度の下限<input type="number" step="0.1" min={0} max={100} value={config.difficulty_min} onChange={e => change({ difficulty_min: Number(e.target.value) })}/></label><label className="field">難易度の上限<input type="number" step="0.1" min={0} max={100} value={config.difficulty_max} onChange={e => change({ difficulty_max: Number(e.target.value) })}/></label></div><label className="field range-label">固定問題の割合 <strong>{Math.round(config.fixed_ratio * 100)}%</strong><input type="range" min={0} max={100} value={config.fixed_ratio * 100} onChange={e => change({ fixed_ratio: Number(e.target.value) / 100 })}/><div className="range-ticks"><span>動的のみ</span><span>固定・動的 50:50</span><span>固定のみ</span></div></label><div className="inline-note">難易度は連続値で保存されます。分野間の実測校正はまだ行っていません。</div></section>
      {frozen && <section className="panel frozen-panel"><div className="panel-title"><h2><Fingerprint size={20}/> 確定した問題セット</h2><span className="badge verified">Frozen</span></div><code className="hash">{frozen.set_hash}</code><p>{frozen.count}問 · 固定{frozen.fixed_count} / 動的{frozen.dynamic_count} · {frozen.duplicate_stats.structures}構造</p><GenerationQualityPanel quality={frozen.generation_quality}/>{frozen.warnings.map(w => <p key={w} className="fine-print">{w}</p>)}<details><summary>問題のプレビュー（正解は表示しません）</summary>{frozen.sample.map(p => <pre key={p.problem_id}>{p.prompt}</pre>)}</details></section>}
    </div><aside className="setup-summary"><section className="panel"><div className="panel-title"><h2>実行プラン</h2><span className="badge preview">{config.custom ? 'Custom' : 'Preview'}</span></div><div className="summary-count numeric">{config.count}<small> 問</small></div><div className="ratio-bar"><span style={{ width: `${config.fixed_ratio * 100}%` }}/></div><div className="ratio-label"><span>固定 {fixedCount}</span><span>動的 {config.count - fixedCount}</span></div><dl><div><dt>選択生成器</dt><dd>{config.generator_ids.length}</dd></div><div><dt>カバレッジ</dt><dd>{coverage} / 16</dd></div><div><dt>難易度</dt><dd>{config.difficulty_min} – {config.difficulty_max}</dd></div><div><dt>モデル</dt><dd>{selectedModels.length}</dd></div><div><dt>推定リクエスト</dt><dd>{config.count * selectedModels.length}</dd></div><div><dt>所要時間</dt><dd>N/A（実測前）</dd></div></dl><div className="inline-note">{coverage < 16 && `未評価の${16 - coverage}分野があります。`}固定問題が不足した場合はセット確定を停止します。</div>{!valid && <p role="status" className="validation">{validation}</p>}<button className="primary full-width" disabled={busy || !valid} onClick={() => void (frozen ? start() : freeze())}>{frozen ? <Play size={17}/> : <Fingerprint size={17}/>} {busy ? '処理中…' : frozen ? `選択した${selectedModels.length}モデルの評価を開始` : '問題セットを確定する'}{!frozen && <ArrowRight size={16}/>}</button><p className="fine-print">確定操作ではモデルを呼びません。課金APIへの自動切り替えはありません。</p></section><section className="panel"><h3>設定を再利用する</h3><label className="field">プリセット名<input value={presetName} disabled={saving} onChange={e => { setPresetName(e.target.value); setSaved(false); }} maxLength={80} placeholder="例：数学を重点評価"/></label><button className="secondary full-width" disabled={!presetName.trim() || saving || saved} onClick={() => void save()}>{saved ? <Check size={16}/> : <Save size={16}/>} {saving ? '保存中…' : saved ? '保存しました' : 'プリセットを保存'}</button></section></aside></div>
  </>;
}
