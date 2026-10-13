import { pct } from './api';
import type { Group } from './types';

export function GroupScores({ title, groups, overlapping = false }: {
  title: string;
  groups?: Record<string, Group>;
  overlapping?: boolean;
}) {
  if (!groups || !Object.keys(groups).length) return null;
  return <section className="panel" aria-label={title}>
    <div className="panel-title"><h2>{title}</h2></div>
    <p className="fine-print">正答率の分母は各グループの全割当問題です。未回答・失敗も含みます。
      {overlapping && '1問が複数のタグに属する場合があります。行同士を合計して総合点にはしません。'}</p>
    <div className="table-scroll"><table>
      <thead><tr><th>グループ</th><th>正解 / 割当数</th><th>処理済み / 割当数</th><th>正答率</th></tr></thead>
      <tbody>{Object.entries(groups).map(([name, group]) => <tr key={name}>
        <td>{name}</td><td>{group.correct} / {group.total}</td>
        <td>{group.completed} / {group.total}</td><td className="numeric">{pct(group.accuracy)}</td>
      </tr>)}</tbody>
    </table></div>
  </section>;
}
