import { seconds } from './api';
import type { Timing } from './types';

export function RunTiming({ timing }: { timing?: Timing }) {
  if (!timing) return null;
  return <section className="panel" aria-label="回答処理時間">
    <div className="panel-title"><h2>回答処理時間</h2></div>
    <dl>
      <div><dt>全確定結果の平均</dt><dd>{seconds(timing.mean_seconds)}</dd></div>
      <div><dt>直近{timing.recent_samples}件の平均</dt><dd>{seconds(timing.recent_mean_seconds)}</dd></div>
      <div><dt>残り回答処理時間の推定</dt><dd>{seconds(timing.remaining_answer_seconds)}</dd></div>
    </dl>
    <p>{timing.reason}</p><p className="fine-print">{timing.scope}</p>
  </section>;
}
