import { useEffect, useState } from 'react';
import { api, ApiError, statusName } from './api';
import type { Run } from './types';

// Only IDs returned by this start operation belong to this group. Keep them in
// the URL so reload/back preserves the group without merging later evaluations.
export function RunBatch({ ids, selected, open, onError }: { ids: string[]; selected: string; open: (id: string) => void; onError: (text: string) => void }) {
  const [missing, setMissing] = useState<string[]>([]);
  const [failed, setFailed] = useState<string[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const key = ids.join(',');
  useEffect(() => {
    let active = true;
    setMissing([]); setFailed([]); setRuns([]);
    const timers = new Set<ReturnType<typeof setTimeout>>();
    // Each model updates independently: one slow request must not hide or
    // stop the progress of every other model in the batch.
    const poll = async (id: string) => {
      let missing = false;
      try {
        const value = await api<Run>(`/runs/${id}?detail=false`);
        if (!active) return;
        setFailed(old => old.filter(item => item !== id));
        setRuns(old => [...old.filter(run => run.id !== id), value]);
      } catch (error) {
        if (!active) return;
        missing = error instanceof ApiError && error.status === 404;
        if (missing) {
          setMissing(old => old.includes(id) ? old : [...old, id]);
          setFailed(old => old.filter(item => item !== id));
        } else setFailed(old => old.includes(id) ? old : [...old, id]);
      }
      if (active && !missing) {
        const timer = setTimeout(() => { timers.delete(timer); void poll(id); }, 2000);
        timers.add(timer);
      }
    };
    key.split(',').forEach(id => void poll(id));
    return () => { active = false; timers.forEach(clearTimeout); };
  }, [key, onError]);
  return <section className="panel" aria-label="今回開始したモデルの評価"><div className="panel-title"><h2>今回の評価 · {ids.length}モデル</h2><span className="muted">モデルを1つずつ順に実行</span></div><div className="table-scroll"><table><thead><tr><th>モデル</th><th>状態</th><th>処理数</th><th>詳細</th></tr></thead><tbody>{ids.map(id => { const run = runs.find(r => r.id === id); return <tr key={id}><td>{run?.model.name ?? ((missing.includes(id) || failed.includes(id)) ? id : '読み込み中…')}</td><td>{missing.includes(id) ? '削除済み・見つかりません' : failed.includes(id) ? '取得失敗 · 再接続中' : run?.execution_block ? `自動停止：${run.execution_block.reason}` : run ? statusName[run.status] : '…'}</td><td>{run ? `${run.completed} / ${run.total}` : '…'}</td><td><button className="secondary" disabled={id === selected || missing.includes(id)} onClick={() => open(id)}>{id === selected ? '表示中' : `${run?.model.name ?? 'このモデル'}の詳細`}</button></td></tr>; })}</tbody></table></div></section>;
}
