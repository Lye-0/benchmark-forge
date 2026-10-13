import { ResultMetrics } from './ResultMetrics';
import { useEffect, useState } from 'react';
import { Download, Pause, Play, RotateCcw, Square } from 'lucide-react';
import { api, pct, seconds, statusName } from './api';
import type { Registry, Run } from './types';

// HTTP snapshots can arrive after newer SSE events, including the final event.
function mergeSnapshot(current: Run | null, next: Run): Run {
  if (current?.id !== next.id) return next;
  if (current.revision > next.revision) return current;
  return { ...current, ...next };
}

export function RunDetail({ id, registry, onError, refresh }: { id: string; registry: Registry; onError: (text: string) => void; refresh: () => Promise<void> }) {
  const [run, setRun] = useState<Run | null>(null);
  const [tab, setTab] = useState('overview');
  const [filter, setFilter] = useState('all');
  const [connection, setConnection] = useState('接続中');
  const [busy, setBusy] = useState(false);
  const [streamEpoch, setStreamEpoch] = useState(0);
  useEffect(() => {
    let active = true;
    const source = new EventSource(`/api/runs/${id}/events`);
    const fetchDetail = () => api<Run>(`/runs/${id}`).then(value => { if (active) setRun(old => mergeSnapshot(old, value)); }).catch(e => { if (active) onError((e as Error).message); });
    void fetchDetail();
    source.addEventListener('progress', e => {
      const value = JSON.parse((e as MessageEvent).data) as Run;
      if (!active) return;
      setConnection('接続済み'); setRun(old => mergeSnapshot(old, value));
      if (['completed', 'cancelled'].includes(value.status)) { source.close(); void fetchDetail(); void refresh(); }
    });
    source.onerror = () => { if (active) setConnection('再接続中 · 保存済み進捗を復元します'); };
    return () => { active = false; source.close(); };
  }, [id, onError, refresh, streamEpoch]);
  const control = async (action: string) => {
    setBusy(true);
    try { await api(`/runs/${id}/${action}`, {}); const value = await api<Run>(`/runs/${id}`); setRun(old => mergeSnapshot(old, value)); if (action === 'retry') setStreamEpoch(old => old + 1); await refresh(); }
    catch (e) { onError((e as Error).message); }
    finally { setBusy(false); }
  };
  useEffect(() => {
    if (tab === 'details') void api<Run>(`/runs/${id}`).then(value => setRun(old => mergeSnapshot(old, value))).catch(e => onError((e as Error).message));
  }, [tab, id, onError]);
  if (!run) return <div className="empty-state">実行結果を読み込み中…</div>;
  const active = ['queued', 'running', 'pausing'].includes(run.status);
  const categoryName = (id: string) => registry.categories.find(c => c.id === id)?.name || id;
  const progress = run.completed / run.total * 100;
  return <>
    <div className="page-heading"><div><div className="eyebrow">{run.provisional ? 'RUN IN PROGRESS' : 'RESULTS OVERVIEW'}</div><h1>{run.model.name}</h1><p><span className={`badge ${run.status}`}>{statusName[run.status]}</span> {run.id}</p></div><div className="button-row">
      {active && <button className="secondary" disabled={busy || run.status === 'pausing'} onClick={() => void control('pause')}><Pause size={16}/> 一時停止</button>}
      {run.status === 'paused' && <button className="primary" disabled={busy} onClick={() => void control('resume')}><Play size={16}/> 再開</button>}
      {(active || run.status === 'paused') && <button className="secondary" disabled={busy} onClick={() => void control('cancel')}><Square size={15}/> 中止</button>}
      {['paused', 'completed'].includes(run.status) && ((run.status_counts.error || 0) + (run.status_counts.timeout || 0) > 0) && <button className="secondary" disabled={busy} onClick={() => void control('retry')}><RotateCcw size={16}/> エラーのみ再試行</button>}
      <a className="secondary" href={`/api/runs/${id}/export/markdown`} download><Download size={16}/> レポート</a>
    </div></div>
    {run.test_only && <div className="inline-note prominent">Mock診断 — ソフトウェアの動作確認用です。LLMの性能値・モデルランキングには含めません。</div>}
    {run.provisional && <section className="panel progress-panel"><div><strong>{run.completed} / {run.total} 問を処理</strong><span>{progress.toFixed(0)}% · {connection}</span></div><div className="progress-track" role="progressbar" aria-label="評価進捗" aria-valuenow={run.completed} aria-valuemin={0} aria-valuemax={run.total}><span style={{ width: `${progress}%` }}/></div><p>正答率は全割当問題を分母とする暫定値です。一時停止・中止は現在の回答処理が終了してから反映されます。</p></section>}
    {!!run.output_diagnostics?.length_limited && <p className="warning" role="note">出力上限による終了: {run.output_diagnostics.length_limited}件（うち無回答: {run.output_diagnostics.empty_length_limited}件）。バックエンドの終了理由に基づく集計です。思考の内容や、上限を増やした場合の正答は判断できません。</p>}
    <div className="tabs" role="tablist" aria-label="結果表示">{[['overview', '概要・分析'], ['details', '問題別ログ'], ['config', '実行条件']].map(([id, label]) => <button key={id} id={`tab-${id}`} role="tab" aria-selected={tab === id} aria-controls={`panel-${id}`} onClick={() => setTab(id)}>{label}</button>)}</div>
    <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
    {tab === 'overview' && <>
      {run.measurement_kind === 'speed' && <p className="warning">専用速度試験：正答率は出力形式の遵守確認です。能力スコアとして比較しません。</p>}<div className="results-stats"><section className="panel accuracy-card"><div className="eyebrow">{run.provisional ? 'PROVISIONAL ACCURACY' : 'COMBINED ACCURACY'}</div><div className="accuracy-value numeric">{(run.accuracy * 100).toFixed(1)}<small>%</small></div><p>カテゴリ均等重みの統合正答率</p><div className="accuracy-foot"><span>{run.correct} 正解 / {run.total} 問</span><span>単純正答率 {pct(run.micro_accuracy)}</span></div></section><section className="panel metric"><span>P50 レイテンシ</span><strong className="numeric">{seconds(run.latency_p50)}</strong><small>回答ごとのE2E時間</small></section><section className="panel metric"><span>P95 レイテンシ</span><strong className="numeric">{seconds(run.latency_p95)}</strong><small>通信・バックエンド処理を含む</small></section><section className="panel metric"><span>正常回答率</span><strong className="numeric">{pct(run.completion_rate)}</strong><small>リソース計測は問題ログに表示</small></section></div>
      <div className="analysis-grid"><section className="panel"><div className="panel-title"><h2>難易度と正答率</h2><span className="badge">未校正</span></div><p className="fine-print">生成難易度の10区間集計。線は回答済み問題のWilson 95%区間で、少数標本の不確実性を示します。</p><svg className="difficulty-chart" viewBox="0 0 640 230" role="img" aria-label="難易度別正答率。各区間の件数と信頼区間は下の表で確認できます">
        {[0, 25, 50, 75, 100].map(v => <g key={v}><line x1="45" y1={185 - v * 1.45} x2="630" y2={185 - v * 1.45} stroke="#252a35"/><text x="5" y={189 - v * 1.45} fill="#939cb0" fontSize="11">{v}%</text></g>)}
        {run.by_difficulty.map((bin, i) => <g key={bin.lower}>{bin.total > 0 && <><rect x={60 + i * 56} y={185 - (bin.accuracy || 0) * 145} width="26" height={(bin.accuracy || 0) * 145} rx="3" fill="#8491ed"/><title>{bin.lower}–{bin.upper}: {pct(bin.accuracy)}, {bin.correct}/{bin.total}</title>{bin.observed_wilson_95 && <><line x1={73 + i * 56} x2={73 + i * 56} y1={185 - bin.observed_wilson_95[0] * 145} y2={185 - bin.observed_wilson_95[1] * 145} stroke="#cbd1ff"/><line x1={69 + i * 56} x2={77 + i * 56} y1={185 - bin.observed_wilson_95[1] * 145} y2={185 - bin.observed_wilson_95[1] * 145} stroke="#cbd1ff"/></>}</>}<text x={65 + i * 56} y="210" fill="#939cb0" fontSize="11">{bin.lower}</text></g>)}<text x="280" y="228" fill="#939cb0" fontSize="11">生成難易度 0–100</text></svg><details><summary>区間ごとのサンプル数・不確実性</summary>{run.difficulty_80 && <p>80%維持の補助推定: {run.difficulty_80.value ?? 'N/A'}。{run.difficulty_80.reason}（各帯20件以上・Wilson下限基準・未校正）</p>}<table><thead><tr><th>難易度</th><th>正解 / 割当数</th><th>回答済み / 割当数</th><th>回答済み標本の95%区間</th></tr></thead><tbody>{run.by_difficulty.map(bin => <tr key={bin.lower}><td>{bin.lower}–{bin.upper}</td><td>{bin.correct}/{bin.total}</td><td>{bin.completed}/{bin.total}</td><td>{bin.observed_wilson_95 ? bin.observed_wilson_95.map(pct).join(' – ') : 'N/A'}</td></tr>)}</tbody></table></details></section>
      <section className="panel"><div className="panel-title"><h2>固定 / 動的の内訳</h2></div>{Object.entries(run.by_origin).map(([origin, group]) => <div className="origin-stat" key={origin}><div><span className={`legend-dot ${origin}`}/><strong>{origin === 'fixed' ? '固定問題' : '動的生成'}</strong><span className="muted">{group.correct} / {group.total} 問</span></div><strong className="numeric">{pct(group.accuracy)}</strong><div className="mini-track"><span style={{ width: `${(group.accuracy || 0) * 100}%` }}/></div><small>統合値への寄与 {(group.weighted_contribution * 100).toFixed(2)}ポイント</small></div>)}<div className="status-breakdown">{['correct', 'incorrect', 'timeout', 'error', 'empty'].map(status => <div key={status}><span>{statusName[status]}</span><strong>{run.status_counts[status] || 0}</strong></div>)}</div></section></div>
      <section className="panel"><div className="panel-title"><h2>カテゴリ別の成績</h2><span className="muted">同一問題のタグを総合点へ重複加算しません</span></div><div className="table-scroll"><table><thead><tr><th>カテゴリ</th><th>正解 / 問題数</th><th>正答率</th><th>統合値への寄与</th></tr></thead><tbody>{Object.entries(run.by_category).map(([id, group]) => <tr key={id}><td>{categoryName(id)}</td><td>{group.correct} / {group.total}</td><td className="numeric">{pct(group.accuracy)}</td><td>{(group.weighted_contribution * 100).toFixed(2)} pt</td></tr>)}</tbody></table></div></section>
      <p className="fine-print">{run.warnings.join(' ')}</p>
    </>}
    {tab === 'details' && <section className="panel"><div className="panel-title"><h2>問題別ログ</h2><div className="button-row"><a className="secondary" href={`/api/runs/${id}/export/csv`} download>CSV</a><a className="secondary" href={`/api/runs/${id}/export/jsonl`} download>JSONL</a><a className="secondary" href={`/api/runs/${id}/archive`} download>全問題・試行アーカイブ</a></div></div><label className="field log-filter">結果を絞り込み<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">すべて</option>{['correct', 'incorrect', 'timeout', 'error', 'empty'].map(s => <option key={s} value={s}>{statusName[s]}</option>)}</select></label>{!run.results?.length && <p className="muted">回答完了後にログを表示します。</p>}{run.results?.filter(r => filter === 'all' || r.status === filter).map(result => <details className="problem-log" key={result.problem_id}><summary><span className={`badge ${result.status}`}>{statusName[result.status]}</span><span>{result.problem.generator_id}<small>{result.problem.origin} · 難易度 {result.problem.target_difficulty.toFixed(1)}</small></span><span className="log-latency">{seconds(result.latency_seconds)}</span></summary>{run.attempts && <details><summary>試行履歴（{run.attempts.filter(a => a.idx === result.index).length}件）</summary>{run.attempts.filter(a => a.idx === result.index).map(a => <div key={a.ordinal}><p>試行 {a.ordinal} · {a.status} · {a.started_at || '旧データ：時刻未記録'}</p>{a.data && <pre>{a.data.answer || a.data.reason}</pre>}</div>)}</details>}<h4>問題</h4><pre>{result.problem.prompt}</pre><div className="answer-grid"><div><h4>モデル回答</h4><pre>{result.answer || '（空文字）'}</pre></div><div><h4>参照解答</h4><pre>{JSON.stringify(result.problem.answer_spec.expected, null, 2)}</pre></div></div><p>{result.reason}</p><dl><div><dt>初回テキスト受信</dt><dd>{seconds(result.ttft_seconds ?? null)}</dd></div><div><dt>出力トークン数</dt><dd>{result.output_tokens ?? "N/A"}</dd></div><div><dt>decode tokens/s</dt><dd>{result.decode_tokens_per_second?.toFixed(2) ?? "N/A"}</dd></div></dl><ResultMetrics metrics={result.metrics}/><small className="muted">{result.problem_id}</small></details>)}</section>}
    {tab === 'config' && <section className="panel"><div className="panel-title"><h2>再現のための実行条件</h2></div><dl><div><dt>問題セットハッシュ</dt><dd><code className="hash">{run.set_hash}</code></dd></div><div><dt>評価経路</dt><dd>{run.model.backend === 'mock' ? 'mock-software-diagnostic' : run.model.backend}</dd></div></dl><h3>モデル・推論設定</h3><pre>{JSON.stringify(run.model, null, 2)}</pre><h3>問題配分</h3><pre>{JSON.stringify(run.config, null, 2)}</pre><h3>リソース計測の概要</h3><pre>{JSON.stringify(run.resources, null, 2)}</pre><h3>実行環境・測定ポリシー</h3><pre>{JSON.stringify(run.environment, null, 2)}</pre></section>}
    </div>
  </>;
}
