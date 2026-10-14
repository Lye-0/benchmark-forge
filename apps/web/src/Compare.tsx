import { useEffect, useRef, useState } from 'react';
import { ArrowRight, GitCompareArrows } from 'lucide-react';
import { api, date, pct, seconds, statusName, measurementName } from './api';
import type { Model, Run } from './types';
import { ReuseSet } from './ReuseSet';
import { CalibrationAnalysis } from './CalibrationAnalysis';

export function Compare({ runs, models, onError, open }: { runs: Run[]; models: Model[]; onError: (text: string) => void; open: (id: string) => void }) {
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<{ comparable: boolean; warnings: string[]; runs: Run[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);
  const compare = async () => {
    const current = ++generation.current;
    setBusy(true);
    try { const result = await api<NonNullable<typeof comparison>>(`/compare?ids=${selected.join(',')}`); if (current === generation.current) setComparison(result); }
    catch (e) { if (current === generation.current) onError((e as Error).message); }
    finally { if (current === generation.current) setBusy(false); }
  };
  return <><div className="page-heading"><div><div className="eyebrow">COMPARE EXPERIMENTS</div><h1>結果を比較</h1><p>問題セット・採点器・推論条件の違いを確認しながら比較します。</p></div><button className="primary" disabled={busy || selected.length < 2 || selected.length > 10} onClick={() => void compare()}><GitCompareArrows size={17}/> {busy ? '比較中…' : '選択した実行を比較'}</button></div><ReuseSet runs={runs} models={models} onCreated={open} onError={onError}/><section className="panel"><div className="panel-title"><h2>比較する実行を選択</h2><span className="muted">{selected.length}件選択 / 2〜10件</span></div>{!runs.length && <div className="empty-state">まず同じセットで複数モデルを評価してください。</div>}{runs.map(run => <label className="model-choice" key={run.id}><input type="checkbox" disabled={selected.length >= 10 && !selected.includes(run.id)} checked={selected.includes(run.id)} onChange={e => { generation.current += 1; setBusy(false); setSelected(e.target.checked ? [...selected, run.id] : selected.filter(id => id !== run.id)); setComparison(null); }}/><span><strong>{run.model.name}</strong><small>{date(run.created_at)} · {statusName[run.status]} · {run.id}</small><small>{measurementName(run.measurement_kind)} · {run.set_hash.slice(0, 16)}… · {run.completed}/{run.total}問</small></span><span className="badge">{run.test_only ? 'Mock診断' : run.model.backend}</span></label>)}</section><CalibrationAnalysis ids={selected} onError={onError}/>{comparison && <section className="panel"><div className="panel-title"><h2>比較結果</h2><span className={`badge ${comparison.comparable ? 'verified' : 'custom'}`}>{comparison.comparable ? '同一問題セット' : '直接比較不可'}</span></div>{comparison.warnings.map(w => <p className="inline-note" key={w}>{w}</p>)}<div className="table-scroll"><table><thead><tr><th>モデル</th><th>正答率・形式遵守率</th><th>P50</th><th>P95</th><th>正常回答率</th><th>PyTorch Peak VRAM（割当量）</th><th>詳細</th></tr></thead><tbody>{comparison.runs.map(run => <tr key={run.id}><td><strong>{run.model.name}</strong><small>{run.model.quantization} · {run.model.backend}</small></td><td className="numeric">{pct(run.accuracy)}{run.measurement_kind === 'speed' && <small>形式遵守率</small>}{run.provisional && <small>暫定</small>}</td><td>{seconds(run.latency_p50)}</td><td>{seconds(run.latency_p95)}</td><td>{pct(run.completion_rate)}</td><td>{typeof run.resources?.peak_vram_allocated_bytes === 'number' ? `${(run.resources.peak_vram_allocated_bytes / 1048576).toFixed(1)} MiB` : 'N/A'}</td><td><button className="icon-button" aria-label={`${run.model.name}の比較詳細`} onClick={() => open(run.id)}><ArrowRight size={16}/></button></td></tr>)}</tbody></table></div><p className="fine-print">Mock診断は順位付けしません。能力と速度・リソースを単一スコアへ合成しません。</p></section>}</>;
}
