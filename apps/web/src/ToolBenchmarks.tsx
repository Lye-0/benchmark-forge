import { useMounted } from './useMounted';
import { useState } from 'react';
import { api } from './api';
import type { Model } from './types';

export function ToolBenchmarks({ models, onCreated, onError, onDiagnosed }: { models: Model[]; onCreated: (id: string) => void; onError: (message: string) => void; onDiagnosed?: () => Promise<void> }) {
  const mounted = useMounted();
  const [mode, setMode] = useState('native-tools');
  const [model, setModel] = useState(() => models.some(m => m.model_id === 'mock-reference' && m.capabilities.available) ? 'mock-reference' : '');
  const eligible = models.filter(m => m.capabilities.available && (mode === 'code' || m.capabilities.native_tools));
  const selected = eligible.find(m => m.model_id === model);
  const [diagnosing, setDiagnosing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const diagnose = async () => {
    setDiagnosing(true); setBusy(true); setStatus("Dockerの隔離と資源制限を実検証しています…");
    try { const result = await api<{ reason: string }>("/sandbox/check", {}); setStatus(result.reason); await onDiagnosed?.(); }
    catch (e) { setStatus(''); mounted.current && onError((e as Error).message); }
    finally { setBusy(false); setDiagnosing(false); }
  };
  const start = async () => {
    if (!selected) return;
    setBusy(true); setStatus('');
    try {
      if (mode === 'code') {
        setStatus('隔離・資源制限を実検証しています…');
        const result = await api<{ available: boolean; reason: string }>('/sandbox/check', {});
        setStatus(result.reason); await onDiagnosed?.();
        if (!result.available) return;
      }
      const frozen = await api<{ set_id: string }>(mode === 'code' ? '/code-sets' : '/tool-sets', { ...(mode === 'code' ? {} : { mode }), count: 5, seed: 42 });
      const result = await api<{ run_ids: string[] }>('/runs', { set_id: frozen.set_id, model_ids: [model] });
      if (mounted.current) onCreated(result.run_ids[0]);
    } catch (e) { setStatus(''); mounted.current && onError((e as Error).message); }
    finally { setBusy(false); setDiagnosing(false); }
  };
  return <section className="panel"><h2>ツール・コードの独立評価</h2><p>テキスト型ツール選択とは別の評価です。仮想在庫は問題ごとにリセットし、外部サービスや実データを操作しません。コードは隔離検証が通ったDocker内だけで実行します。</p><div className="form-grid"><label className="field">独立評価モード<select value={mode} disabled={busy} onChange={e => { const next = e.target.value; setMode(next); if (!models.some(m => m.model_id === model && m.capabilities.available && (next === 'code' || m.capabilities.native_tools))) setModel(''); setStatus(''); }}><option value="native-tools">ネイティブツール呼出</option><option value="agent">複数ターンの仮想在庫</option><option value="code">Pythonコード生成・隔離採点</option></select></label><label className="field">独立評価モデル<select value={model} disabled={busy} onChange={e => setModel(e.target.value)}><option value="">モデルを選択してください</option>{models.map(m => <option key={m.model_id} value={m.model_id} disabled={!m.capabilities.available || (mode !== 'code' && !m.capabilities.native_tools)}>{m.name}</option>)}</select></label></div><p className="fine-print">通常評価・仮想ツール評価にはDockerもWSL2も不要です。コード評価にはDocker DesktopのLinuxコンテナ、またはLinuxのDocker Engineが必要です。</p><button className="secondary" disabled={busy} onClick={() => void diagnose()}>{diagnosing ? 'Dockerを検証中…' : 'コード実行用Dockerを検証'}</button><button className="secondary" disabled={busy || !selected} onClick={() => void start()}>{busy && !diagnosing ? '開始中…' : '独立評価を開始（5問）'}</button>{status && <p role="status">{status}</p>}</section>;
}
