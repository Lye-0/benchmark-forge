import { useEffect, useRef, useState } from 'react';
import { api, pct } from './api';

interface Analysis {
  model_count: number;
  item_count: number;
  category_count: number;
  warnings: string[];
  by_difficulty: { lower: number; upper: number; items: number; observations: number; observed_accuracy: number | null }[];
}

export function CalibrationAnalysis({ ids, onError }: { ids: string[]; onError: (message: string) => void }) {
  const [result, setResult] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const key = ids.join(',');
  useEffect(() => {
    generation.current += 1;
    setResult(null);
    setBusy(false);
    return () => { generation.current += 1; };
  }, [key]);
  const analyze = async () => {
    const current = ++generation.current;
    setBusy(true);
    setResult(null);
    try {
      const data = await api<Analysis>(`/calibration-analysis?ids=${encodeURIComponent(key)}`);
      if (current === generation.current) setResult(data);
    } catch (error) {
      if (current === generation.current) onError((error as Error).message);
    } finally {
      if (current === generation.current) setBusy(false);
    }
  };
  return <section className="panel">
    <h2>校正に向けた観測の点検</h2>
    <p>上で選択した、同じ問題セットの実モデルの完了ランを集計します。同じモデルの再実行は1件だけ選んでください。</p>
    <button className="secondary" disabled={busy || ids.length < 2 || ids.length > 10} onClick={() => void analyze()}>{busy ? '集計中…' : '選択したランの観測を集計'}</button>
    {result && <>
      <p role="status">{result.model_count}モデルの観測 · {result.item_count}問 · {result.category_count}/16カテゴリ · 難易度は未校正</p>
      <div className="table-scroll"><table><thead><tr><th>暫定難易度帯</th><th>問題数</th><th>観測数</th><th>観測正答率</th></tr></thead><tbody>{result.by_difficulty.map(bin => <tr key={bin.lower}><td>{bin.lower}〜{bin.upper}{bin.upper === 100 ? '（上端含む）' : '未満'}</td><td>{bin.items}</td><td>{bin.observations}</td><td>{bin.observed_accuracy == null ? 'N/A' : pct(bin.observed_accuracy)}</td></tr>)}</tbody></table></div>
      {result.warnings.map(warning => <p className="fine-print" key={warning}>{warning}</p>)}
    </>}
  </section>;
}
