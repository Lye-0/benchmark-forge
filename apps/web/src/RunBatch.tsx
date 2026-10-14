import { useEffect, useState } from 'react';
import { api, statusName } from './api';
import type { Run } from './types';

// Only IDs returned by this start operation belong to this group. Keep them in
// the URL so reload/back preserves the group without merging later evaluations.
export function RunBatch({ ids, selected, open, onError }: { ids: string[]; selected: string; open: (id: string) => void; onError: (text: string) => void }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const key = ids.join(',');
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const values = await Promise.all(key.split(',').map(id => api<Run>(`/runs/${id}?detail=false`)));
        if (active) setRuns(values);
      } catch (e) { if (active) onError((e as Error).message); }
      if (active) timer = setTimeout(() => void poll(), 2000);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [key, onError]);
  return <section className="panel" aria-label="今回開始したモデルの評価"><div className="panel-title"><h2>今回の評価 · {ids.length}モデル</h2><span className="muted">モデルを1つずつ順に実行</span></div><div className="table-scroll"><table><thead><tr><th>モデル</th><th>状態</th><th>処理数</th><th>詳細</th></tr></thead><tbody>{ids.map(id => { const run = runs.find(r => r.id === id); return <tr key={id}><td>{run?.model.name ?? '読み込み中…'}</td><td>{run ? statusName[run.status] : '…'}</td><td>{run ? `${run.completed} / ${run.total}` : '…'}</td><td><button className="secondary" disabled={id === selected} onClick={() => open(id)}>{id === selected ? '表示中' : `${run?.model.name ?? 'このモデル'}の詳細`}</button></td></tr>; })}</tbody></table></div></section>;
}
