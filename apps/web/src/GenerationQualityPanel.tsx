import { pct } from './api';
import type { GenerationQuality } from './types';

export function GenerationQualityPanel({ quality }: { quality?: GenerationQuality | null }) {
  if (!quality) return null;
  return <details className="panel"><summary>問題の生成品質 · {quality.structures}構造 / {quality.adopted}問</summary><p>採択率 {pct(quality.adoption_rate)} · 重複率 {pct(quality.duplicate_rate)}（{quality.candidate_attempts}候補）</p><p>完全一致による除外 {quality.surface_rejected}件 · 入力の並べ替えによる同値の除外 {quality.semantic_rejected}件 · 同じ構造の反復 {quality.repeated_structures}件</p><div className="table-scroll"><table><thead><tr><th>構造テンプレート</th><th>問題数</th></tr></thead><tbody>{Object.entries(quality.structure_counts).map(([name, count]) => <tr key={name}><td>{name}</td><td>{count}</td></tr>)}</tbody></table></div><p className="fine-print">{quality.scope}</p></details>;
}
