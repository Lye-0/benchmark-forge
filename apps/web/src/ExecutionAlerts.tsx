import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api';

interface Block { id: string; model_name: string; reason: string; detected_at: string }
const blockKey = (block: Block) => `${block.id}:${block.detected_at}`;

// Monitor durable stops across all pages, including models other than the open run.
export function ExecutionAlerts({ onChanged }: { onChanged: () => Promise<void> }) {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [dismissed, setDismissed] = useState<string[]>([]);
  const [startError, setStartError] = useState('');
  const [actionError, setActionError] = useState('');
  const [monitorError, setMonitorError] = useState('');
  const [busy, setBusy] = useState(false);
  const mounted = useRef(false);
  const generation = useRef(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const refresh = useCallback(async () => {
    const version = ++generation.current;
    try {
      const result = await api<Block[]>('/execution-blocks');
      if (mounted.current && version === generation.current) { setBlocks(result); setMonitorError(''); }
    } catch { if (mounted.current && version === generation.current) setMonitorError('自動停止の通知を取得できません。接続を再確認しています。'); }
  }, []);
  useEffect(() => {
    mounted.current = true;
    let timer: ReturnType<typeof setTimeout>;
    let active = true;
    const poll = async () => { await refresh(); if (active) timer = setTimeout(() => void poll(), 2000); };
    void poll();
    const failedStart = (event: Event) => setStartError((event as CustomEvent<string>).detail);
    window.addEventListener('forge-start-unavailable', failedStart);
    return () => { mounted.current = false; generation.current += 1; active = false; clearTimeout(timer); window.removeEventListener('forge-start-unavailable', failedStart); };
  }, [refresh]);
  const current = blocks.find(block => !dismissed.includes(blockKey(block)));
  const key = startError || (current ? blockKey(current) : '');
  useEffect(() => {
    if (!key) return;
    setActionError('');
    const node = dialog.current;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    node?.showModal();
    return () => { node?.close(); document.body.style.overflow = overflow; };
  }, [key]);
  const close = () => {
    if (startError) setStartError('');
    else if (current) setDismissed(old => [...old, blockKey(current)]);
  };
  const control = async (action: 'resume' | 'cancel') => {
    if (!current) return;
    setBusy(true); setActionError('');
    try {
      await api(`/runs/${current.id}/${action}`, {});
      if (mounted.current) setDismissed(old => [...old, blockKey(current)]);
      await refresh(); await onChanged();
    } catch (error) { if (mounted.current) setActionError((error as Error).message); }
    finally { if (mounted.current) setBusy(false); }
  };
  return <>
    {monitorError && <p role="status" className="inline-note">{monitorError}</p>}
    {blocks.length > 0 && <div className="error-banner"><span>モデルを実行できず、{blocks.length}件の評価が一時停止しています。</span><button className="secondary" onClick={() => setDismissed([])}>停止理由を確認</button></div>}
    {key && <dialog ref={dialog} className="model-dialog" aria-label={startError ? '評価を開始できません' : 'モデルの評価を自動停止しました'} onCancel={event => { event.preventDefault(); if (!busy) close(); }}>
      <h2>{startError ? '評価を開始できません' : 'モデルの評価を自動停止しました'}</h2>
      {startError ? <p>{startError}</p> : current && <><h3>{current.model_name}</h3><p>{current.reason}</p><p>完了済みの回答は保存されています。接続・モデルの状態を確認して再開すると、実行できなかった問題から続けます。</p><p className="fine-print">他のモデルの評価は、それぞれの接続状態に応じて進みます。</p></>}
      {actionError && <p role="alert" className="error-banner">{actionError}</p>}
      <div className="button-row">
        {!startError && <><button className="primary" disabled={busy} onClick={() => void control('resume')}>{busy ? '処理中…' : '接続を確認して再開'}</button><button className="secondary" disabled={busy} onClick={() => void control('cancel')}>このモデルの評価を中止</button></>}
        <button className="secondary" autoFocus disabled={busy} onClick={close}>閉じる</button>
      </div>
    </dialog>}
  </>;
}
