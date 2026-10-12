import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, Search } from 'lucide-react';
import type { Category, Generator } from './types';

function Check({ label, ids, selected, toggle }: { label: string; ids: string[]; selected: string[]; toggle: (ids: string[], checked: boolean) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const count = ids.filter(id => selected.includes(id)).length;
  useEffect(() => { if (ref.current) ref.current.indeterminate = count > 0 && count < ids.length; }, [count, ids.length]);
  return <input ref={ref} type="checkbox" aria-label={label} disabled={!ids.length} checked={ids.length > 0 && count === ids.length} onChange={e => toggle(ids, e.target.checked)} />;
}

export function allGenerators(categories: Category[]): Generator[] {
  return categories.flatMap(c => c.subcategories.flatMap(s => s.generators));
}

export function CategoryTree({ categories, selected, onChange, readOnly = false }: { categories: Category[]; selected: string[]; onChange: (ids: string[]) => void; readOnly?: boolean }) {
  const [search, setSearch] = useState('');
  const [closed, setClosed] = useState<string[]>([]);
  const [closedSubs, setClosedSubs] = useState<string[]>([]);
  const toggle = (ids: string[], checked: boolean) => {
    if (readOnly) return;
    onChange(checked ? [...new Set([...selected, ...ids])] : selected.filter(id => !ids.includes(id)));
  };
  const needle = search.toLocaleLowerCase();
  const all = allGenerators(categories).filter(g => g.status === 'verified').map(g => g.id);
  return <div className={`category-tree ${readOnly ? 'readonly' : ''}`}>
    <div className="tree-toolbar"><label className="search"><Search size={16}/><input aria-label="カテゴリ・生成器を検索" placeholder="カテゴリ・生成器を検索…" value={search} onChange={e => setSearch(e.target.value)}/></label><button type="button" onClick={() => setClosed([])}>すべて展開</button><button type="button" onClick={() => setClosed(categories.map(c => c.id))}>折りたたむ</button></div>
    {!readOnly && <div className="tree-actions"><span>{selected.length} / {all.length} 生成器を選択</span><div><button type="button" onClick={() => onChange(all)}>すべて選択</button><button type="button" onClick={() => onChange([])}>解除</button></div></div>}
    <div className="tree-scroll">{categories.map(category => {
      const categoryMatch = category.name.toLocaleLowerCase().includes(needle);
      const subs = category.subcategories.map(s => ({ ...s, generators: s.generators.filter(g => categoryMatch || s.name.toLocaleLowerCase().includes(needle) || `${g.id} ${g.name}`.toLocaleLowerCase().includes(needle)) })).filter(s => s.generators.length);
      if (needle && !categoryMatch && !subs.length) return null;
      const ids = category.subcategories.flatMap(s => s.generators.filter(g => g.status === 'verified').map(g => g.id));
      const open = needle.length > 0 || !closed.includes(category.id);
      return <div className="tree-category" key={category.id}>
        <div className="tree-row parent"><button type="button" className="icon-button" aria-label={`${category.name}を${open ? '閉じる' : '開く'}`} aria-expanded={open} onClick={() => setClosed(open ? [...closed, category.id] : closed.filter(id => id !== category.id))}>{open ? <ChevronDown size={15}/> : <ChevronRight size={15}/>}</button>
          {!readOnly && <Check label={category.name} ids={ids} selected={selected} toggle={toggle}/>}<span className="category-number">{category.id}</span><span>{category.name}</span><span className="tree-count">{ids.length ? `${selected.filter(id => ids.includes(id)).length}/${ids.length}` : '未対応'}</span>
        </div>
        {open && (ids.length ? subs.map(sub => {
          const key = `${category.id}:${sub.id}`;
          const subOpen = needle.length > 0 || !closedSubs.includes(key);
          return <div className="subcategory" key={key}><div className="tree-row"><button type="button" className="icon-button" aria-label={`${sub.name}の生成器を${subOpen ? '閉じる' : '開く'}`} aria-expanded={subOpen} onClick={() => setClosedSubs(subOpen ? [...closedSubs, key] : closedSubs.filter(x => x !== key))}>{subOpen ? <ChevronDown size={13}/> : <ChevronRight size={13}/>}</button>{!readOnly && <Check label={`${category.name} / ${sub.name}`} ids={sub.generators.map(g => g.id)} selected={selected} toggle={toggle}/>}<span>{sub.name}</span></div>
            {subOpen && sub.generators.map(g => <label className="tree-row generator" key={g.id}>{!readOnly && <input type="checkbox" checked={selected.includes(g.id)} disabled={g.status !== 'verified'} onChange={e => toggle([g.id], e.target.checked)}/>}<span>{g.name}<small>{g.id} · v{g.version}</small></span><span className="badge verified">{g.status}</span><small className="difficulty-range">0–100</small></label>)}</div>;
        }) : <p className="unavailable-note">検証済み生成器はまだありません。別分野への代替は行いません。</p>)}
      </div>;
    })}</div>
  </div>;
}
