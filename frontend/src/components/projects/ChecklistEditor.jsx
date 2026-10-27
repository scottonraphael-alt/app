import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';

export default function ChecklistEditor({ value, onChange }) {
  const [title,setTitle]=useState('');
  const add=()=>{
    if (!title.trim() || value.length >= 50) return;
    const id=globalThis.crypto?.randomUUID?.() || `step-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    onChange([...value,{id,title:title.trim(),done:false}]); setTitle('');
  };
  return <fieldset className="pj-checklist-editor pj-wide"><legend>Checklist · facultatif <span>{value.length}/50</span></legend><p className="pj-help">Découpez le résultat en petites étapes. Le membre les cochera depuis la tâche avant de rendre son travail.</p>
    {!!value.length && <ol>{value.map((item,index)=><li key={item.id}><span>{index+1}</span><input aria-label={`Étape ${index+1}`} maxLength={160} required value={item.title} onChange={e=>onChange(value.map(v=>v.id===item.id?{...v,title:e.target.value}:v))}/><button type="button" className="pj-icon pj-danger" aria-label={`Retirer l’étape ${index+1}`} onClick={()=>onChange(value.filter(v=>v.id!==item.id))}><Trash2 size={15}/></button></li>)}</ol>}
    <div className="pj-checklist-add"><input aria-label="Nouvelle étape de la checklist" maxLength={160} value={title} disabled={value.length>=50} onChange={e=>setTitle(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();add();}}} placeholder="Ex. Tester le matériel"/><button type="button" className="pj-btn" disabled={!title.trim() || value.length>=50} onClick={add}><Plus size={15}/> Ajouter l’étape</button></div>
  </fieldset>;
}
