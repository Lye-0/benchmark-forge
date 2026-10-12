export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail : '入力・接続状態を確認してください';
    throw new Error(detail);
  }
  return response.json();
}
export const pct = (value: number | null) => value === null ? 'N/A' : `${(value * 100).toFixed(1)}%`;
export const seconds = (value: number | null) => value === null ? 'N/A' : `${value.toFixed(3)} s`;
export const date = (value: string) => new Date(value).toLocaleString('ja-JP');
export const statusName: Record<string, string> = { queued: '待機中', running: '実行中', pausing: '停止処理中', paused: '一時停止', completed: '完了', cancelled: '中止', correct: '正解', incorrect: '不正解', timeout: 'タイムアウト', error: 'エラー', empty: '無回答', ungradable: '採点不可' };
