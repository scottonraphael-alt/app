import {useState} from 'react';
import {MarkdownField} from '../announcements/Editors';
import {Markdown} from '../announcements/Preview';
import {safeUrl} from '../announcements/document';
import '../../DiscordAnnouncements.css';
const PANELS={
 'public:verification':'Accueil · Vérification','public:contact_staff':'Accueil · Contact Staff','public:support':'Accueil · Soutien','public:moderation':'Accueil · Modération',
 'room:verification':'Ticket · Vérification','room:contact_staff':'Ticket · Contact Staff','room:summons':'Ticket · Convocation',
 'request:support':'Demande de soutien en attente','room:bubble':'Ticket · Bulle','room:support':'Ticket · Soutien','review:support':'Demande de soutien traitée',
};
const empty=()=>({color:'#78618c',blocks:[]});
const VARIABLES=[
 ['membre','Membre concerné','@Membre'],
 ['interlocuteur','Intervenant actuellement attribué ; sinon « Non attribué »','@Helper'],
 ['traite_par','Personne ayant accepté ou refusé ; sinon « Décision en attente »','@Staff'],
 ['date_traitement','Date de la décision ; sinon « Décision en attente »','30 octobre 2026 à 15:00'],
 ['salon','Lien vers le salon ; sinon « Salon en préparation »','#soutient-membre'],
];
const previewText=text=>(text||'').replace(/\{(membre|interlocuteur|traite_par|date_traitement|salon)\}/g,(_,key)=>VARIABLES.find(v=>v[0]===key)[2]);

export default function WorkflowPanelEditor({value={},onChange,catalogue}){
 const [key,setKey]=useState('public:support');
 const panel=value[key]||empty();
 const update=next=>onChange({...value,[key]:next});
 const blocks=panel.blocks||[];
 const change=(index,patch)=>update({...panel,blocks:blocks.map((b,i)=>i===index?{...b,...patch}:b)});
 const move=(index,delta)=>{const next=[...blocks];[next[index],next[index+delta]]=[next[index+delta],next[index]];update({...panel,blocks:next});};
 return <section className="wf-panel-editor">
 <p className="cz-eyebrow">COMPOSER · MESSAGES DISCORD</p><h2>Vos panneaux, votre ton</h2>
 <p>Composez les textes, vignettes à droite, séparateurs, images et liens. Dans un ticket personnalisé, votre contenu remplace l’en-tête et le pied de page d’origine. Le sélecteur de gestion et les avertissements d’accès sont conservés. Sans bloc personnalisé, le texte d’origine est conservé.</p>
 <div className="wf-grid"><label>Panneau à personnaliser<select value={key} onChange={e=>setKey(e.target.value)}>{Object.entries(PANELS).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
 <label>Couleur du panneau<input type="color" value={panel.color} onChange={e=>update({...panel,color:e.target.value})}/></label></div>
 {key.startsWith('room:')&&<><label className="wf-heading-option"><input type="checkbox" checked={!!panel.replace_heading} onChange={e=>update({...panel,replace_heading:e.target.checked})}/> Exiger la mention du membre dans le titre</label><p>Insérez <code>{'{membre}'}</code> dans un titre ou un texte : il sera remplacé par la mention du membre concerné.</p></>}
 {key==='room:summons'&&<button type="button" className="cw-button" onClick={()=>update({color:'#ed4245',replace_heading:true,blocks:[{kind:'section',text:"# 🛡️ Convocation de {membre}\n\nTu fais l'objet d'une convocation par l'équipe de modération. Merci de prendre connaissance de ce message et de rester disponible dans ce ticket afin de faire le point.",url:'',label:''},{kind:'separator',text:'',url:'',label:''}]})}>Utiliser le modèle Convocation avec vignette</button>}
 <details className="wf-variable-help"><summary>Variables et phrases reconnues par Iris</summary>
 <p>Les variables sont remplacées dans les blocs texte et texte + vignette des tickets et demandes. Les panneaux publics ne connaissent pas encore le membre.</p>
 <dl>{VARIABLES.map(([name,label])=><div key={name}><dt><code>{'{'+name+'}'}</code></dt><dd>{label}</dd></div>)}</dl>
 <p><code>{'{avatar_membre}'}</code> : avatar du membre concerné, à insérer dans le champ image ou vignette de tout type de ticket. Si l’avatar est indisponible, une image Discord par défaut est utilisée.</p>
 <h3>Phrases reconnues à l’import d’un ancien salon</h3>
 <ul><li><code>Soutien de @membre</code> : identifie la personne aidée.</li>
 <li><code>Ton Interlocuteur est @helper</code> : attribution initiale au helper mentionné, s’il possède le rôle Helper ou Helper+.</li>
 <li><code>Pris en charge par @staff</code> : intervenant des autres dossiers importés.</li>
 <li><code>Convocation de @membre</code>, <code>Contact Staff de @membre</code>, <code>Vérification de @membre</code> et <code>Bulle d’échange de @membre</code> : membre du dossier correspondant.</li></ul>
 <p>Utilisez une vraie mention Discord, pas un pseudo tapé à la main. La lecture porte sur le panneau d’ouverture reconnu. « Traité par » est une information d’affichage, pas une commande d’attribution.</p>
 <p><strong>Tickets créés par Iris :</strong> l’attribution est enregistrée lors de la prise en charge. Modifier le texte ne réattribue personne. Une synchronisation ne doit pas écraser une réattribution ou une désattribution manuelle.</p>
 </details>
 <div className="wf-panel-grid"><div>{blocks.map((b,index)=><article className="wf-block" key={index}>
 <div className="wf-block-toolbar"><strong>Bloc {index+1} · {({text:'Texte',section:'Texte + vignette à droite',separator:'Séparateur',image:'Image',link:'Lien'})[b.kind]}</strong>
 <button type="button" className="cw-button" disabled={!index} onClick={()=>move(index,-1)} aria-label={'Monter le bloc '+(index+1)}>↑</button>
 <button type="button" className="cw-button" disabled={index===blocks.length-1} onClick={()=>move(index,1)} aria-label={'Descendre le bloc '+(index+1)}>↓</button>
 <button type="button" className="cw-button cw-danger" onClick={()=>update({...panel,blocks:blocks.filter((_,i)=>i!==index)})}>Retirer</button></div>
 {['text','section'].includes(b.kind)&&<MarkdownField label={'Texte du bloc '+(index+1)} value={b.text||''} catalogue={catalogue} onChange={text=>change(index,{text})}/>}
 {['image','section','link'].includes(b.kind)&&<label>{b.kind!=='link'?'Lien HTTPS de l’image':'Destination du bouton'}<input type={b.url==='{avatar_membre}'?'text':'url'} value={b.url||''} onChange={e=>change(index,{url:e.target.value})}/></label>}
 {['text','section'].includes(b.kind)&&!key.startsWith('public:')&&<div className="cw-toolbar" aria-label="Insérer une variable">{VARIABLES.map(([name,label])=><button type="button" className="cw-button" key={name} title={label} onClick={()=>change(index,{text:(b.text||'')+' {'+name+'}'})}>{'{'+name+'}'}</button>)}{key==='room:support'&&<button type="button" className="cw-button" onClick={()=>change(index,{text:(b.text||'')+'\nTon Interlocuteur est {interlocuteur}'})}>Phrase d’attribution</button>}</div>}
 {['image','section'].includes(b.kind)&&!key.startsWith('public:')&&<button type="button" className="cw-button" onClick={()=>change(index,{url:'{avatar_membre}'})}>Utiliser l’avatar du membre</button>}
 {b.kind==='image'&&<label>Description de l’image<input maxLength={700} value={b.text||''} onChange={e=>change(index,{text:e.target.value})}/></label>}
 {b.kind==='link'&&<label>Texte du bouton<input maxLength={80} value={b.label||''} onChange={e=>change(index,{label:e.target.value})}/></label>}
 </article>)}
 <div className="cw-toolbar">{[['text','Texte'],['section','Texte + vignette'],['separator','Séparateur'],['image','Image'],['link','Lien']].map(([kind,label])=><button type="button" className="cw-button" key={kind} disabled={blocks.length>=5} onClick={()=>update({...panel,blocks:[...blocks,{kind,text:['text','section'].includes(kind)?'Votre message ici.':'',url:'',label:''}]})}>+ {label}</button>)}</div>
 <small>5 blocs et 700 caractères maximum, pour laisser place aux informations du dossier.</small>
 <p>Enregistrez les réglages ci-dessous. Les nouveaux panneaux utiliseront ce contenu. Pour remplacer un panneau public existant, relancez sa commande /panel.</p>
 <button type="button" className="cw-button" onClick={()=>{const next={...value};delete next[key];onChange(next);}}>Rétablir le contenu d’origine</button>
 </div><aside className="wf-panel-preview an-discord-preview"><p className="cz-eyebrow">APERÇU DU CONTENU PERSONNALISÉ</p><div className="an-preview-container" style={{borderLeftColor:panel.color}}>
 {!blocks.length&&<p>Le panneau conserve sa présentation d’origine.</p>}
 {blocks.map((b,i)=><div key={i}>{b.kind==='text'?<Markdown text={previewText(b.text)} catalogue={catalogue}/>:b.kind==='section'?<div className="wf-section-preview"><Markdown text={previewText(b.text)} catalogue={catalogue}/>{(safeUrl(b.url,true)||b.url==='{avatar_membre}')?<img src={b.url==='{avatar_membre}'?'https://cdn.discordapp.com/embed/avatars/0.png':b.url} alt="Vignette à droite" referrerPolicy="no-referrer"/>:<span className="wf-thumbnail-empty">Vignette</span>}</div>:b.kind==='separator'?<hr/>:b.kind==='image'?<div className="an-preview-media">{(safeUrl(b.url,true)||b.url==='{avatar_membre}')?<img src={b.url==='{avatar_membre}'?'https://cdn.discordapp.com/embed/avatars/0.png':b.url} alt={b.text||"Aperçu du média"} referrerPolicy="no-referrer"/>:<span>🖼 Image à choisir</span>}</div>:<span className="an-discord-button">{b.label||'Bouton de lien'} ↗</span>}</div>)}
 <hr/>{key==='room:support'&&<p>🤝 Ton Interlocuteur est <strong>@Helper</strong></p>}<small>Aperçu avec des valeurs fictives. Les variables seront remplacées et le sélecteur de gestion sera ajouté dans Discord.</small></div></aside></div></section>;
}
