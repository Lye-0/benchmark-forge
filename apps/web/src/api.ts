export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail) ? data.detail.map((item: { loc?: (string | number)[]; msg?: string }) => `${item.loc?.filter(x => x !== 'body').join('.') || '入力'}: ${item.msg || '値を確認してください'}`).join(' / ') : `リクエストに失敗しました（HTTP ${response.status}）。再試行してください`;
    if (data.code === 'execution_unavailable' && path === '/runs') window.dispatchEvent(new CustomEvent('forge-start-unavailable', { detail }));
    throw new ApiError(detail, response.status);
  }
  return response.json();
}
export const pct = (value: number | null) => value === null ? 'N/A' : `${(value * 100).toFixed(1)}%`;
export const seconds = (value: number | null) => value === null ? 'N/A' : `${value.toFixed(3)} s`;
export const date = (value: string) => new Date(value).toLocaleString('ja-JP');
export const statusName: Record<string, string> = { execution_unavailable: '実行不能・未採点', interrupted: '中断', queued: '待機中', running: '実行中', pausing: '停止処理中', paused: '一時停止', completed: '完了', cancelled: '中止', correct: '正解', incorrect: '不正解', timeout: 'タイムアウト', error: 'エラー', empty: '無回答', ungradable: '採点不可' };

export const measurementName = (kind?: string) => ({ text: 'テキスト評価', speed: '速度試験（形式遵守率）', 'native-tools': 'ツール呼出評価', agent: '複数ターン評価', code: 'コード評価' }[kind ?? 'text'] ?? kind);
