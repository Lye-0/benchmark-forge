import { useEffect, useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { api } from './api';

export function DeleteButton({ path, title, description, onDeleted }: { path: string; title: string; description: string; onDeleted: () => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.current?.showModal();
    return () => { document.body.style.overflow = overflow; };
  }, [open]);
  const close = () => { dialog.current?.close(); setOpen(false); };
  const remove = async () => {
    setBusy(true); setError('');
    try { await api(path, {}); close(); await onDeleted(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <><button className="secondary" onClick={() => { setError(''); setOpen(true); }}><Trash2 size={15}/>削除</button>{open && <dialog ref={dialog} className="model-dialog delete-dialog" aria-label={title} onCancel={event => { event.preventDefault(); if (!busy) close(); }}><h2>{title}</h2><p>{description}</p>{error && <p role="alert">{error}</p>}<div className="button-row"><button className="secondary" autoFocus disabled={busy} onClick={close}>キャンセル</button><button className="primary" disabled={busy} onClick={() => void remove()}>{busy ? '削除中…' : '削除する'}</button></div></dialog>}</>;
}
