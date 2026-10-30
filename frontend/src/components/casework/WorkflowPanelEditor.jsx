import {useState} from 'react';
import {MarkdownField} from '../announcements/Editors';
import {Markdown} from '../announcements/Preview';
import {safeUrl} from '../announcements/document';
import '../../DiscordAnnouncements.css';
const PANELS={
 'public:verification':'Accueil · Vérification','public:contact_staff':'Accueil · Contact Staff','public:support':'Accueil · Soutien',
 'room:verification':'Ticket · Vérification','room:contact_staff':'Ticket · Contact Staff','room:summons':'Ticket · Convocation',
 'request:support':'Demande de soutien en attente','room:bubble':'Ticket · Bulle','room:support':'Ticket · Soutien','review:support':'Demande de soutien traitée',
};
const empty=()=>({color:'#78618c',blocks:[]});
export default function WorkflowPanelEditor({value={},onChange,catalogue}){
 const [key,setKey]=useState('public:support');
 const panel=value[key]||empty();
 const update=next=>onChange({...value,[key]:next});
 const blocks=panel.blocks||[];
 const change=(index,patch)=>update({...panel,blocks:blocks.map((b,i)=>i===index?{...b,...patch}:b)});
 const move=(index,delta)=>{const next=[...blocks];[next[index],next[index+delta]]=[next[index+delta],next[index]];update({...panel,blocks:next});};
 return <section className="wf-panel-editor">
 <p className="cz-eyebrow">COMPOSER · MESSAGES DISCORD</p><h2>Vos panneaux, votre ton</h2>
 <p>Composez les textes, séparateurs, images et liens. Les identités, motifs, permissions et actions du dossier restent ajoutés automatiquement. Sans bloc personnalisé, le texte d’origine est conservé.</p>
 <div className="wf-grid"><label>Panneau à personnaliser<select value={key} onChange={e=>setKey(e.target.value)}>{Object.entries(PANELS).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
 <label>Couleur du panneau<input type="color" value={panel.color} onChange={e=>update({...panel,color:e.target.value})}/></label></div>
 <div className="wf-panel-grid"><div>{blocks.map((b,index)=><article className="wf-block" key={index}>
 <div className="wf-block-toolbar"><strong>Bloc {index+1} · {({text:'Texte',separator:'Séparateur',image:'Image',link:'Lien'})[b.kind]}</strong>
 <button type="button" className="cw-button" disabled={!index} onClick={()=>move(index,-1)} aria-label={'Monter le bloc '+(index+1)}>↑</button>
 <button type="button" className="cw-button" disabled={index===blocks.length-1} onClick={()=>move(index,1)} aria-label={'Descendre le bloc '+(index+1)}>↓</button>
 <button type="button" className="cw-button cw-danger" onClick={()=>update({...panel,blocks:blocks.filter((_,i)=>i!==index)})}>Retirer</button></div>
 {b.kind==='text'&&<MarkdownField label={'Texte du bloc '+(index+1)} value={b.text||''} catalogue={catalogue} onChange={text=>change(index,{text})}/>}
 {['image','link'].includes(b.kind)&&<label>{b.kind==='image'?'Lien HTTPS de l’image':'Destination du bouton'}<input type="url" value={b.url||''} onChange={e=>change(index,{url:e.target.value})}/></label>}
 {b.kind==='image'&&<label>Description de l’image<input maxLength={700} value={b.text||''} onChange={e=>change(index,{text:e.target.value})}/></label>}
 {b.kind==='link'&&<label>Texte du bouton<input maxLength={80} value={b.label||''} onChange={e=>change(index,{label:e.target.value})}/></label>}
 </article>)}
 <div className="cw-toolbar">{[['text','Texte'],['separator','Séparateur'],['image','Image'],['link','Lien']].map(([kind,label])=><button type="button" className="cw-button" key={kind} disabled={blocks.length>=5} onClick={()=>update({...panel,blocks:[...blocks,{kind,text:kind==='text'?'Votre message ici.':'',url:'',label:''}]})}>+ {label}</button>)}</div>
 <small>5 blocs et 700 caractères maximum, pour laisser place aux informations du dossier.</small>
 <p>Enregistrez les réglages ci-dessous. Les nouveaux panneaux utiliseront ce contenu. Pour remplacer un panneau public existant, relancez sa commande /panel.</p>
 <button type="button" className="cw-button" onClick={()=>{const next={...value};delete next[key];onChange(next);}}>Rétablir le contenu d’origine</button>
 </div><aside className="wf-panel-preview an-discord-preview"><p className="cz-eyebrow">APERÇU DU CONTENU PERSONNALISÉ</p><div className="an-preview-container" style={{borderLeftColor:panel.color}}>
 {!blocks.length&&<p>Le panneau conserve sa présentation d’origine.</p>}
 {blocks.map((b,i)=><div key={i}>{b.kind==='text'?<Markdown text={b.text} catalogue={catalogue}/>:b.kind==='separator'?<hr/>:b.kind==='image'?<div className="an-preview-media">{safeUrl(b.url,true)?<img src={b.url} alt={b.text||"Aperçu du média"} referrerPolicy="no-referrer"/>:<span>🖼 Image à choisir</span>}</div>:<span className="an-discord-button">{b.label||'Bouton de lien'} ↗</span>}</div>)}
 <hr/><small>Les informations du dossier et les actions apparaîtront ici dans Discord.</small></div></aside></div></section>;
}
