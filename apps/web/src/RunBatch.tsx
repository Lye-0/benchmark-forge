import { useEffect, useState } from 'react';
import { api, statusName } from './api';
import type { Run } from './types';

// Only IDs returned by this start operation belong to this group. Keep them in
// the URL so reload/back preserves the group without merging later evaluations.
export function RunBatch({ ids, selected, open, onError }: { ids: string[]; selected: string; open: (id: string) => void; onError: (text: string) => void }) {
  const [failed, setFailed] = useState<string[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const key = ids.join(',');
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const runIds = key.split(',');
      const values = await Promise.allSettled(runIds.map(id => api<Run>(`/runs/${id}?detail=false`)));
      if (active) {
        setFailed(runIds.filter((_, index) => values[index].status === 'rejected'));
        setRuns(old => runIds.flatMap((id, index) => { const result = values[index]; return result.status === 'fulfilled' ? [result.value] : old.filter(run => run.id === id); }));
      }
      if (active) timer = setTimeout(() => void poll(), 2000);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [key, onError]);
  return <section className="panel" aria-label="今回開始したモデルの評価"><div className="panel-title"><h2>今回の評価 · {ids.length}モデル</h2><span className="muted">モデルを1つずつ順に実行</span></div><div className="table-scroll"><table><thead><tr><th>モデル</th><th>状態</th><th>処理数</th><th>詳細</th></tr></thead><tbody>{ids.map(id => { const run = runs.find(r => r.id === id); return <tr key={id}><td>{run?.model.name ?? (failed.includes(id) ? id : '読み込み中…')}</td><td>{failed.includes(id) ? '取得失敗 · 再接続中' : run ? statusName[run.status] : '…'}</td><td>{run ? `${run.completed} / ${run.total}` : '…'}</td><td><button className="secondary" disabled={id === selected} onClick={() => open(id)}>{id === selected ? '表示中' : `${run?.model.name ?? 'このモデル'}の詳細`}</button></td></tr>; })}</tbody></table></div></section>;
}
