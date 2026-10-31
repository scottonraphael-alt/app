import {useState} from 'react';
import {MarkdownField} from '../announcements/Editors';
import {Markdown} from '../announcements/Preview';
import {safeUrl} from '../announcements/document';
import '../../DiscordAnnouncements.css';
const PANELS={
 'anonymous:review':'Messages anonymes · Validation Staff',
 'form:verification':'Vérification · Formulaire complet (fil)',
 'staff:verification':'Vérification · Mini-panneau Staff (salon)',
 'public:verification':'Accueil · Vérification','public:contact_staff':'Accueil · Contact Staff','public:support':'Accueil · Soutien','public:moderation':'Accueil · Modération',
 'room:verification':'Ticket · Vérification','room:contact_staff':'Ticket · Contact Staff','room:summons':'Ticket · Convocation',
 'request:support':'Demande de soutien en attente','room:bubble':'Ticket · Bulle','room:support':'Ticket · Soutien','review:support':'Demande de soutien traitée',
};
const empty=()=>({color:'#78618c',blocks:[]});
const VARIABLES=[
 ['identifiant_anonyme','Identifiant permanent et anonyme','ANO-AB12-CD'],
 ['message_anonyme','Texte complet proposé par le membre','Voici le message anonyme à valider.'],
 ['avis_ia','Résumé du préavis disponible, sinon état non généré','Le formulaire nécessite une lecture attentive du Staff.'],
 ['membre','Membre concerné','@Membre'],
 ['interlocuteur','Intervenant actuellement attribué ; sinon « Non attribué »','@Helper'],
 ['traite_par','Personne ayant accepté ou refusé ; sinon « Décision en attente »','@Staff'],
 ['date_traitement','Date de la décision ; sinon « Décision en attente »','30 octobre 2026 à 15:00'],
 ['salon','Lien vers le salon ; sinon « Salon en préparation »','#soutient-membre'],
];
const previewText=text=>(text||'').replace(/\{(membre|interlocuteur|traite_par|date_traitement|salon|avis_ia|identifiant_anonyme|message_anonyme)\}/g,(_,key)=>VARIABLES.find(v=>v[0]===key)[2]);

export default function WorkflowPanelEditor({value={},onChange,catalogue,panelCatalogue=PANELS}){
 const [key,setKey]=useState('public:support');
 const panel=value[key]||empty();
 const limit=key==='anonymous:review'?3500:key.startsWith('public:')?4000:key.startsWith('room:')?3600:({'form:verification':2000,'staff:verification':3000,'request:support':1200,'review:support':1400}[key]||3600);
 const sizes={membre:24,interlocuteur:24,traite_par:24,date_traitement:40,salon:95,avis_ia:300,identifiant_anonyme:11,message_anonyme:3000};
 const used=(panel.blocks||[]).filter(b=>['text','section'].includes(b.kind)).reduce((n,b)=>n+(b.text||'').replace(/\{(membre|interlocuteur|traite_par|date_traitement|salon|avis_ia|identifiant_anonyme|message_anonyme)\}/g,(_,name)=>'x'.repeat(sizes[name])).length,0);
 const update=next=>onChange({...value,[key]:next});
 const blocks=panel.blocks||[];
 const change=(index,patch)=>update({...panel,blocks:blocks.map((b,i)=>i===index?{...b,...patch}:b)});
 const move=(index,delta)=>{const next=[...blocks];[next[index],next[index+delta]]=[next[index+delta],next[index]];update({...panel,blocks:next});};
 return <section className="wf-panel-editor">
 <p className="cz-eyebrow">COMPOSER · MESSAGES DISCORD</p><h2>Vos panneaux, votre ton</h2>
 <p>Composez les textes, vignettes à droite, séparateurs, images et liens. Dans un ticket personnalisé, votre contenu remplace l’en-tête et le pied de page d’origine. Le sélecteur de gestion et les avertissements d’accès sont conservés. Sans bloc personnalisé, le texte d’origine est conservé.</p>
 <div className="wf-grid"><label>Panneau à personnaliser<select value={key} onChange={e=>setKey(e.target.value)}>{Object.entries(panelCatalogue).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
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
 {key==='anonymous:review'&&<div className="cw-guide"><p>Conservez <code>{'{message_anonyme}'}</code> : le texte doit être lisible avant validation. L’identifiant, l’état et les boutons sont ajoutés automatiquement. Le bouton Révéler reste présent après un refus et ne fonctionne que pour les Responsables.</p></div>}
 <div className="wf-panel-grid"><div>{blocks.map((b,index)=><article className="wf-block" key={index}>
 <div className="wf-block-toolbar"><strong>Bloc {index+1} · {({text:'Texte',section:'Texte + vignette à droite',separator:'Séparateur',image:'Image',link:'Lien'})[b.kind]}</strong>
 <button type="button" className="cw-button" disabled={!index} onClick={()=>move(index,-1)} aria-label={'Monter le bloc '+(index+1)}>↑</button>
 <button type="button" className="cw-button" disabled={index===blocks.length-1} onClick={()=>move(index,1)} aria-label={'Descendre le bloc '+(index+1)}>↓</button>
 <button type="button" className="cw-button cw-danger" onClick={()=>update({...panel,blocks:blocks.filter((_,i)=>i!==index)})}>Retirer</button></div>
 {['text','section'].includes(b.kind)&&<MarkdownField label={'Texte du bloc '+(index+1)} value={b.text||''} catalogue={catalogue} onChange={text=>change(index,{text})}/>}
 {['image','section','link'].includes(b.kind)&&<label>{b.kind!=='link'?'Lien HTTPS de l’image':'Destination du bouton'}<input type={b.url==='{avatar_membre}'?'text':'url'} value={b.url||''} onChange={e=>change(index,{url:e.target.value})}/></label>}
 {['text','section'].includes(b.kind)&&!key.startsWith('public:')&&<div className="cw-toolbar" aria-label="Insérer une variable">{VARIABLES.filter(([name])=>key==='anonymous:review'?['identifiant_anonyme','message_anonyme','traite_par','date_traitement'].includes(name):!['identifiant_anonyme','message_anonyme'].includes(name)&&(name!=='avis_ia'||['form:verification','staff:verification'].includes(key))).map(([name,label])=><button type="button" className="cw-button" key={name} title={label} onClick={()=>change(index,{text:(b.text||'')+' {'+name+'}'})}>{'{'+name+'}'}</button>)}{key==='room:support'&&<button type="button" className="cw-button" onClick={()=>change(index,{text:(b.text||'')+'\nTon Interlocuteur est {interlocuteur}'})}>Phrase d’attribution</button>}</div>}
 {['image','section'].includes(b.kind)&&!key.startsWith('public:')&&key!=='anonymous:review'&&<button type="button" className="cw-button" onClick={()=>change(index,{url:'{avatar_membre}'})}>Utiliser l’avatar du membre</button>}
 {b.kind==='image'&&<label>Description de l’image<input maxLength={1024} value={b.text||''} onChange={e=>change(index,{text:e.target.value})}/></label>}
 {b.kind==='link'&&<label>Texte du bouton<input maxLength={80} value={b.label||''} onChange={e=>change(index,{label:e.target.value})}/></label>}
 </article>)}
 <div className="cw-toolbar">{[['text','Texte'],['section','Texte + vignette'],['separator','Séparateur'],['image','Image'],['link','Lien']].map(([kind,label])=><button type="button" className="cw-button" key={kind} disabled={blocks.length>=5} onClick={()=>update({...panel,blocks:[...blocks,{kind,text:['text','section'].includes(kind)?(key==='anonymous:review'?'{message_anonyme}':'Votre message ici.'):'',url:'',label:''}]})}>+ {label}</button>)}</div>
 <p role="status" className={used>limit?"cw-alert":""}><strong>{used.toLocaleString("fr-FR")} / {limit.toLocaleString("fr-FR")} caractères</strong> · 5 blocs maximum. Les variables sont comptées avec leur taille maximale. La place restante est réservée aux informations automatiques.</p>
 <p>Enregistrez les réglages ci-dessous : les panneaux déjà publiés seront actualisés automatiquement dans les secondes qui suivent, sans nouvelle commande ni notification. Un message supprimé volontairement ne sera pas recréé.</p>
 <button type="button" className="cw-button" onClick={()=>{const next={...value};delete next[key];onChange(next);}}>Rétablir le contenu d’origine</button>
 </div><aside className="wf-panel-preview an-discord-preview"><p className="cz-eyebrow">APERÇU DU CONTENU PERSONNALISÉ</p><div className="an-preview-container" style={{borderLeftColor:panel.color}}>
 {!blocks.length&&<p>Le panneau conserve sa présentation d’origine.</p>}
 {blocks.map((b,i)=><div key={i}>{b.kind==='text'?<Markdown text={previewText(b.text)} catalogue={catalogue}/>:b.kind==='section'?<div className="wf-section-preview"><Markdown text={previewText(b.text)} catalogue={catalogue}/>{(safeUrl(b.url,true)||b.url==='{avatar_membre}')?<img src={b.url==='{avatar_membre}'?'https://cdn.discordapp.com/embed/avatars/0.png':b.url} alt="Vignette à droite" referrerPolicy="no-referrer"/>:<span className="wf-thumbnail-empty">Vignette</span>}</div>:b.kind==='separator'?<hr/>:b.kind==='image'?<div className="an-preview-media">{(safeUrl(b.url,true)||b.url==='{avatar_membre}')?<img src={b.url==='{avatar_membre}'?'https://cdn.discordapp.com/embed/avatars/0.png':b.url} alt={b.text||"Aperçu du média"} referrerPolicy="no-referrer"/>:<span>🖼 Image à choisir</span>}</div>:<span className="an-discord-button">{b.label||'Bouton de lien'} ↗</span>}</div>)}
 <hr/>{key==='room:support'&&<p>🤝 Ton Interlocuteur est <strong>@Helper</strong></p>}<small>Aperçu avec des valeurs fictives. Les variables seront remplacées et le sélecteur de gestion sera ajouté dans Discord.</small></div></aside></div></section>;
}
