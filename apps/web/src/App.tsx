import { useCallback, useEffect, useState } from 'react';
import { Activity, ArrowRight, Boxes, ChartNoAxesCombined, CheckCircle2, Cpu, FlaskConical, GitCompareArrows, LayoutDashboard, Menu, Plus, Settings2, ShieldCheck, X } from 'lucide-react';
import { api, date, pct, statusName } from './api';
import { CategoryTree } from './CategoryTree';
import { NewBenchmark } from './NewBenchmark';
import { RunBatch } from './RunBatch';
import { RunDetail } from './RunDetail';
import { ModelManager } from './ModelManager';
import { ToolBenchmarks } from './ToolBenchmarks';
import { SpeedProbe } from './SpeedProbe';
import { HoldoutImport } from './HoldoutImport';
import { GpuDiagnostics } from './GpuDiagnostics';
import { Compare } from './Compare';
import type { Model, Preset, Registry, Run, Settings } from './types';

const navigation = [
  { id: 'dashboard', name: 'ダッシュボード', icon: LayoutDashboard },
  { id: 'new', name: '新しいベンチマーク', icon: Plus },
  { id: 'history', name: '実行履歴', icon: Activity },
  { id: 'compare', name: '結果を比較', icon: GitCompareArrows },
  { id: 'models', name: 'モデル', icon: Cpu },
  { id: 'generators', name: '生成器・カバレッジ', icon: Boxes },
  { id: 'settings', name: 'プロファイル・設定', icon: Settings2 },
];

export function RunTable({ runs, open }: { runs: Run[]; open: (id: string) => void }) {
  if (!runs.length) return <div className="empty-state"><ChartNoAxesCombined size={32}/><h3>まだ実行結果がありません</h3><p>問題セットを確定して、最初の診断を始めましょう。</p></div>;
  return <div className="table-scroll"><table><thead><tr><th>モデル / 実行</th><th>状態</th><th>正答率</th><th>処理数</th><th>日時</th><th><span className="sr-only">詳細</span></th></tr></thead><tbody>{runs.map(run => <tr key={run.id}><td><strong>{run.model.name}</strong><small>{run.id.slice(0, 16)}… {run.test_only && '· Mock診断'}</small></td><td><span className={`badge ${run.status}`}>{statusName[run.status]}</span></td><td><strong className="numeric">{pct(run.accuracy)}</strong>{run.provisional && <small>暫定</small>}</td><td className="numeric">{run.completed} / {run.total}</td><td>{date(run.created_at)}</td><td><button className="icon-button" aria-label={`${run.model.name}の詳細`} onClick={() => open(run.id)}><ArrowRight size={18}/></button></td></tr>)}</tbody></table></div>;
}

export function App() {
  const [page, setPage] = useState(window.location.hash.slice(1) || 'dashboard');
  const [mobile, setMobile] = useState(false);
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [models, setModels] = useState<Model[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [torchStatus, setTorchStatus] = useState('');
  const [checkingTorch, setCheckingTorch] = useState(false);
  const checkTorch = async () => { setCheckingTorch(true); try { const r = await api<{ reason: string }>('/environment/torch', {}); setTorchStatus(r.reason); } catch (e) { setError((e as Error).message); } finally { setCheckingTorch(false); } };
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const navigate = (id: string) => { window.location.hash = id; setPage(id); setMobile(false); setError(''); };
  useEffect(() => { const onHash = () => setPage(window.location.hash.slice(1) || 'dashboard'); window.addEventListener('hashchange', onHash); return () => window.removeEventListener('hashchange', onHash); }, []);
  const refresh = useCallback(async () => {
    try {
      const [r, m, history, p, s] = await Promise.all([api<Registry>('/registry'), api<Model[]>('/models'), api<Run[]>('/runs'), api<Preset[]>('/presets'), api<Settings>('/settings')]);
      setRegistry(r); setModels(m); setRuns(history); setPresets(p); setSettings(s);
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh, page]);
  const openRun = (id: string) => navigate(`run/${id}`);
  const runId = page.slice(4).split('?')[0];
  const batchIds = new URLSearchParams(page.split('?')[1]).get('batch')?.split(',').filter(Boolean) ?? [];
  const openBatch = (ids: string[], selected = ids[0]) => navigate(`run/${selected}${ids.length > 1 ? `?batch=${ids.join(',')}` : ''}`);
  const title = page.startsWith('run/') ? '実行結果' : navigation.find(n => n.id === page)?.name || 'ダッシュボード';

  return <div className="app-shell">
    <a href="#main" className="skip-link" onClick={e => { e.preventDefault(); document.getElementById('main')?.focus(); }}>本文へ移動</a>
    <aside className={`sidebar ${mobile ? 'visible' : ''}`}>
      <button className="brand" onClick={() => navigate('dashboard')}><span className="brand-mark"><FlaskConical size={22}/></span><span>benchmark<span className="brand-second">forge</span><small>LLM BENCHMARK LAB</small></span></button>
      <div className="nav-label">WORKSPACE</div><nav aria-label="メインナビゲーション">{navigation.map(({ id, name, icon: Icon }) => <button key={id} aria-current={page === id ? 'page' : undefined} className={`nav-item ${page === id ? 'active' : ''}`} onClick={() => navigate(id)}><Icon size={18}/><span>{name}</span>{id === 'new' && <span className="nav-dot"/>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="local-status"><span className="status-dot"/>LOCAL WORKSPACE</div><p>データはローカルに保存。<br/>再現できる評価から始める。</p><div className="sidebar-version"><span>Preview v1</span><span>v0.1.0</span></div></div>
    </aside>
    {mobile && <button className="sidebar-overlay" aria-label="メニューを閉じる" onClick={() => setMobile(false)}/>}
    <div className="workspace">
      <header className="topbar"><div><button className="icon-button mobile-menu" aria-label="メニューを開く" onClick={() => setMobile(true)}><Menu size={20}/></button><span className="breadcrumb">Workspace <span>/</span> <strong>{title}</strong></span></div><div className="topbar-meta"><span className="badge preview">PREVIEW</span><span className="local-label"><ShieldCheck size={14}/> Local-first</span></div></header>
      <main id="main" tabIndex={-1}>
        {error && <div role="alert" className="error-banner"><span>{error}</span><button aria-label="エラーを閉じる" className="icon-button" onClick={() => setError('')}><X size={16}/></button></div>}
        {loading ? <div className="empty-state"><Activity size={28}/><p>ワークスペースを読み込み中…</p></div> : !registry ? <div className="empty-state"><h2>APIに接続できません</h2><p>バックエンドの起動状態を確認してください。</p><button className="primary" onClick={() => void refresh()}>再接続</button></div> : <>
          {page === 'dashboard' && <>
            <div className="page-heading"><div><div className="eyebrow">YOUR RESEARCH WORKSPACE</div><h1>ベンチマークを、確かな比較へ。</h1><p>生成から評価、分析まで。再現可能なLLM評価のワークスペース。</p></div><button className="primary" onClick={() => navigate('new')}><Plus size={18}/> 新しいベンチマーク</button></div>
            <div className="stats-grid"><Stat icon={<Cpu size={19}/>} label="登録モデル" value={String(models.length)} note="Mockを含む / 実モデルは接続確認が必要"/><Stat icon={<Boxes size={19}/>} label="検証済み生成器" value={String(registry.generator_count)} note="LLMを使わない決定的生成"/><Stat icon={<ChartNoAxesCombined size={19}/>} label="カテゴリカバレッジ" value={`${registry.covered_categories}`} suffix="/ 16" note="未対応の分野は代替しません"/><Stat icon={<CheckCircle2 size={19}/>} label="完了したラン" value={String(runs.filter(r => r.status === 'completed').length)} note="診断とモデル評価を区別して保存"/></div>
            <div className="dashboard-row"><section className="panel intro-panel"><span className="badge preview">REPRODUCIBLE BY DESIGN</span><h2>同じ問題で、違いを見る。</h2><p>固定問題とシード付きの生成問題をひとつのセットに。<br/>セットを確定してから、モデルを順に評価します。</p><div className="workflow"><span><b>01</b>設定</span><ArrowRight size={15}/><span><b>02</b>セット確定</span><ArrowRight size={15}/><span><b>03</b>評価・分析</span></div><button className="text-button" onClick={() => navigate('new')}>クイック診断を設定する <ArrowRight size={16}/></button></section><section className="panel methodology"><div className="panel-title"><h2>評価の前提</h2><ShieldCheck size={18}/></div><dl><div><dt>プロファイル</dt><dd>Preview v1</dd></div><div><dt>難易度</dt><dd>連続値 0–100 · 未校正</dd></div><div><dt>既定の固定 / 動的</dt><dd>50% / 50%</dd></div><div><dt>生成コード実行</dt><dd className="muted">{settings?.sandbox.available ? '隔離検証済み' : '実行前の隔離検証が必要'}</dd></div></dl><p className="fine-print">能力スコアと速度・メモリは独立した指標です。Mock診断はモデル性能を表しません。</p></section></div>
            <section className="panel"><div className="panel-title"><div><h2>最近の実行</h2><p>保存された問題セットと結果をいつでも確認。</p></div><button className="text-button" onClick={() => navigate('history')}>すべて見る <ArrowRight size={16}/></button></div><RunTable runs={runs.slice(0, 5)} open={openRun}/></section>
          </>}
          {page === 'new' && <NewBenchmark registry={registry} models={models} presets={presets} onCreated={openBatch} refresh={refresh} onError={setError}/>}
          {page === 'history' && <><div className="page-heading"><div><div className="eyebrow">RUN HISTORY</div><h1>実行履歴</h1><p>完了・中断したランを、同じ問題セットとともに追跡。</p></div><button className="secondary" onClick={() => void refresh()}>更新</button></div><section className="panel"><RunTable runs={runs} open={openRun}/></section></>}
          {page.startsWith('run/') && <>{batchIds.length > 1 && <RunBatch ids={batchIds} selected={runId} open={id => openBatch(batchIds, id)} onError={setError}/>}<RunDetail key={runId} id={runId} registry={registry} onError={setError} refresh={refresh}/></>}
          {page === 'compare' && <Compare runs={runs} models={models} onError={setError} open={openRun}/>}
          {page === 'models' && <ModelManager models={models} refresh={refresh} onError={setError}/>}
          {page === 'generators' && <><div className="page-heading"><div><div className="eyebrow">GENERATOR REGISTRY</div><h1>生成器・カバレッジ</h1><p>16大カテゴリを管理。検証済みの構造から少しずつ広げます。</p></div><span className="badge verified">{registry.generator_count} verified</span></div><section className="panel"><div className="panel-title"><h2>{registry.covered_categories} / 16 カテゴリをカバー</h2><span className="muted">難易度は未校正</span></div><CategoryTree categories={registry.categories} selected={[]} onChange={() => {}} readOnly/></section></>}
          {page === 'settings' && settings && <><div className="page-heading"><div><div className="eyebrow">PROFILES & SETTINGS</div><h1>プロファイル・設定</h1><p>ローカルデータ、安全性、評価プロファイルの状態。</p></div></div><ToolBenchmarks models={models} onCreated={openRun} onError={setError}/><SpeedProbe models={models} onCreated={openRun} onError={setError}/><HoldoutImport models={models} onCreated={openRun} onError={setError}/><div className="settings-grid"><section className="panel"><div className="panel-title"><h2>保存されたプリセット</h2></div>{presets.map(p => <div className="setting-row" key={p.id}><div><strong>{p.name}</strong><small>{p.config.count}問 · 固定{Math.round(p.config.fixed_ratio * 100)}% · seed {p.config.seed}</small></div><span className="badge">{p.config.custom ? 'Custom' : 'Preview'}</span></div>)}</section><div><section className="panel"><div className="panel-title"><h2>実行環境・データ</h2><ShieldCheck size={18}/></div><dl><div><dt>実行OS</dt><dd>{settings.host?.os ?? "N/A"}</dd></div><div><dt>CPU</dt><dd>{settings.host?.cpu_model ?? "N/A"}</dd></div><div><dt>GPU構成</dt><dd>{settings.host?.gpu_devices?.map(g => `${g.name} / driver ${g.driver_version ?? 'N/A'}`).join(", ") || settings.host?.gpu_inventory_reason || "N/A"}</dd></div><div><dt>GPU診断</dt><dd>{settings.host?.gpu_inventory_reason || "構成情報を取得済み（推論での使用は未確認）"}</dd></div><div><dt>保存先</dt><dd><code>{settings.data_directory}</code></dd></div><div><dt>有料API契約</dt><dd>不要</dd></div><div><dt>コードライセンス</dt><dd>{settings.code_license}</dd></div></dl><button className="secondary" disabled={checkingTorch} onClick={() => void checkTorch()}>{checkingTorch ? "確認中…" : "PyTorch / CUDAを確認"}</button>{torchStatus && <p role="status">{torchStatus}</p>}<GpuDiagnostics/><p className="fine-print">DBには参照解答とモデル回答を含みます。個人の履歴・モデル重み・認証情報はGitに含めません。</p></section><section className="panel"><div className="panel-title"><h2>隔離・Codex接続</h2><span className="badge">{settings.sandbox.available ? 'コード隔離検証済み' : '未検証'}</span></div><p>{settings.sandbox.reason}</p><p className="fine-print">Codex CLI / App Serverの公式イベントはMock検証対象です。実接続・サインインはNOT_VERIFIED。公式プレビュー条件と安全な隔離の確認が必要です。</p></section></div></div></>}
        </>}
        <footer><span>Benchmark Forge <span className="footer-dot">·</span> Local LLM research</span><span>Preview · 生成難易度は未校正</span></footer>
      </main>
    </div>
  </div>;
}

function Stat({ icon, label, value, suffix, note }: { icon: React.ReactNode; label: string; value: string; suffix?: string; note: string }) {
  return <section className="panel stat"><div className="stat-label">{label}<span>{icon}</span></div><div className="stat-value numeric">{value}<small>{suffix}</small></div><p>{note}</p></section>;
}
