import { seconds } from './api';

export function ResultMetrics({ metrics }: { metrics?: Record<string, unknown> }) {
  if (!metrics || !Object.keys(metrics).length) return null;
  const memory = (value: unknown) => typeof value === 'number' ? `${(value / 1048576).toFixed(1)} MiB` : 'N/A';
  return <><h4>{metrics.mode ? '仮想ツールの実行記録' : metrics.sandbox_status ? '隔離コードの実行記録' : 'バックエンドの計測'}</h4>{'load_seconds' in metrics && <><dl><div><dt>モデルロード時間</dt><dd>{seconds(typeof metrics.load_seconds === 'number' ? metrics.load_seconds : null)}</dd></div><div><dt>生成時間（prefillを含む）</dt><dd>{seconds(typeof metrics.generation_seconds === 'number' ? metrics.generation_seconds : null)}</dd></div><div><dt>ワーカー Peak RAM</dt><dd>{memory(metrics.peak_ram_bytes)}</dd></div><div><dt>PyTorch Peak VRAM（割当量）</dt><dd>{memory(metrics.peak_vram_allocated_bytes)}</dd></div></dl><p className="fine-print">問題ごとにモデルをロード。GPU全体の使用量ではありません。decode速度・TTFTは未計測です。</p></>}{metrics.mode && <p>モード: {String(metrics.mode)} · 呼出回数: {String(metrics.tool_calls ?? 'N/A')} · 禁止操作: {metrics.policy_violation ? '検出' : 'なし'}</p>}{metrics.sandbox_status && <p>隔離実行: {String(metrics.sandbox_status)} · 終了コード: {String(metrics.sandbox_exit_code ?? 'N/A')}</p>}<details><summary>計測条件・実行トレース</summary><pre>{JSON.stringify(metrics, null, 2)}</pre></details></>;
}
