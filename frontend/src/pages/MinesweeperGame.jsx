import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,Bomb,Check,Flag,MousePointer2,RotateCcw,ShieldCheck,Timer,Users,Volume2,VolumeX} from 'lucide-react';
import {useBoardSounds} from './useBoardSounds';
import './MinesweeperGame.css';

const LEVELS={easy:'Découverte',medium:'Intermédiaire',hard:'Expert'};
function clock(seconds){const value=Math.max(0,Math.floor(seconds));return `${Math.floor(value/60)}:${String(value%60).padStart(2,'0')}`;}
function description(value){return typeof value==='number'?(value?`${value} mine${value>1?'s':''} autour`:'case vide'):({hidden:'case fermée',flag:'drapeau posé',mine:'mine',hit:'mine déclenchée',wrong:'drapeau incorrect'}[value]);}

export default function MinesweeperGame({state,userId,canControl,connected,send,error,onInvite}){
 const game=state.minesweeper;
 const [flagMode,setFlagMode]=useState(false),[focused,setFocused]=useState(0),[confirm,setConfirm]=useState(false);
 const [now,setNow]=useState(performance.now());
 const cancel=useRef(null),trigger=useRef(null);
 const me=game.seats.find(s=>s.id===userId);
 const playing=game.phase==='playing',finished=game.phase==='finished',won=game.result?.reason==='cleared';
 const playable=connected&&playing&&Boolean(me)&&!game.paused;
 const elapsed=game.elapsed+(playing&&game.started&&!game.paused?(now-state.at)/1000:0);
 const remaining=game.mine_count-game.flag_count;
 const sounds=useBoardSounds('minesweeper',game.round_id,game.revision,connected);
 useEffect(()=>{if(!playing||!game.started||game.paused)return undefined;const id=setInterval(()=>setNow(performance.now()),250);return()=>clearInterval(id);},[playing,game.started,game.paused]);
 useEffect(()=>{setFlagMode(false);setFocused(0);},[game.round_id,game.columns,game.rows]);
 useEffect(()=>{
  if(!confirm)return undefined;
  const previous=document.activeElement;cancel.current?.focus();
  const onKey=e=>{
   if(e.key==='Escape')setConfirm(false);
   if(e.key==='Tab'){
    if(e.shiftKey&&document.activeElement===cancel.current){e.preventDefault();trigger.current?.focus();}
    else if(!e.shiftKey&&document.activeElement===trigger.current){e.preventDefault();cancel.current?.focus();}
   }
  };
  document.addEventListener('keydown',onKey);return()=>{document.removeEventListener('keydown',onKey);previous?.focus();};
 },[confirm]);
 function action(kind,extra={}){sounds.unlock();send({type:'ms_'+kind,round_id:game.round_id,revision:game.revision,...extra});}
 function cellAction(cell,value,forceFlag=false){
  if(!playable)return;
  if(value==='hidden'||value==='flag'){
   const flag=forceFlag||flagMode;
   if(flag)action('flag',{cell});
   else if(value==='hidden')action('reveal',{cell});
  }else if(typeof value==='number'&&value>0&&!forceFlag){action('chord',{cell});}
 }
 function keyboard(event){
  const cell=Number(event.target.dataset.cell);
  if(!Number.isInteger(cell))return;
  if(event.key.toLowerCase()==='f'||event.key===' '){event.preventDefault();cellAction(cell,game.board.flat()[cell],true);return;}
  const delta={ArrowLeft:-1,ArrowRight:1,ArrowUp:-game.columns,ArrowDown:game.columns}[event.key];
  if(!delta)return;
  event.preventDefault();const next=Math.max(0,Math.min(game.rows*game.columns-1,cell+delta));
  event.currentTarget.querySelector(`[data-cell="${next}"]`)?.focus();
 }
 const status=!connected?'Reconnexion à OasisGame…':game.phase==='lobby'?'Choisis ta place, puis explore la grille.':game.paused?'La grille attend votre retour · pause de 2 minutes maximum':finished?(won?'Toutes les cases sûres ont été découvertes !':game.result?.reason==='abandoned'?'La partie s’est arrêtée après votre départ.':'Une mine a été déclenchée. On réessaie ?'):!me?'Tu observes la partie.':game.started?'Un chiffre, un indice. À vous de jouer.':'Votre premier clic et les cases autour sont protégés.';
 return <main className="mw-page">
  <header className="mw-header"><span className="og-brand">✦ OasisGame</span><div><button aria-label={sounds.enabled?'Couper les sons':'Activer les sons'} onClick={sounds.toggle}>{sounds.enabled?<Volume2 size={17}/>:<VolumeX size={17}/>}</button>{onInvite&&game.settings.mode==='coop'&&<button onClick={onInvite}><Users size={16}/> Inviter</button>}{canControl&&<button disabled={!connected} onClick={()=>playing?setConfirm(true):send({type:'choose_game',game:'menu'})}><ArrowLeft size={16}/> Tous les jeux</button>}</div></header>
  <div className="mw-heading"><div><small>UN PEU DE LOGIQUE, BEAUCOUP DE CALME</small><h1>Démineur</h1><p>Explore, observe et fais confiance aux indices.</p></div><span className="mw-mode"><Users size={16}/>{game.settings.mode==='solo'?'Solo':`Coopération · ${game.seats.length}/8`}</span></div>
  {error&&<p className="og-error" role="alert">{error}</p>}
  <div className={'mw-status'+(won?' mw-win':'')} role="status"><span aria-hidden="true">{won?'✦':'◇'}</span>{status}</div>
  <div className="mw-layout"><section className="mw-stage" aria-label="Grille et commandes du démineur">
   <div className="mw-toolbar"><div className="mw-counter"><Flag size={18}/><strong>{remaining}</strong><span>drapeaux restants</span></div><div className="mw-counter"><Timer size={18}/><strong aria-label="Temps écoulé">{clock(elapsed)}</strong></div><span className="mw-level">{LEVELS[game.settings.difficulty]} · {game.columns} × {game.rows}</span></div>
   <div className={'mw-board-shell'+(finished?(won?' mw-cleared':' mw-lost'):'')} tabIndex={0} aria-label="Zone de grille défilante">
    <div className="mw-grid" style={{'--mw-columns':game.columns}} role="group" aria-label={`Grille du démineur, ${game.rows} lignes et ${game.columns} colonnes`} onKeyDown={keyboard}>
     {game.board.flatMap((row,r)=>row.map((value,c)=>{const cell=r*game.columns+c,closed=value==='hidden',flagged=value==='flag';
      return <button key={cell} type="button" data-cell={cell} className={`mw-cell mw-value-${value}${won&&flagged?' mw-correct':''}`}
       tabIndex={cell===focused?0:-1} onFocus={()=>setFocused(cell)} aria-label={`Ligne ${r+1}, colonne ${c+1} : ${description(value)}`}
       aria-disabled={!playable||(!closed&&!flagged&&!(typeof value==='number'&&value>0))}
       onClick={()=>cellAction(cell,value)} onContextMenu={e=>{e.preventDefault();cellAction(cell,value,true);}}>
       {typeof value==='number'?(value||null):flagged?<Flag aria-hidden="true"/>:value==='mine'||value==='hit'?<Bomb aria-hidden="true"/>:value==='wrong'?<span aria-hidden="true">×</span>:null}
      </button>;
     }))}
    </div>
   </div>
   {game.columns>12&&<p className="mw-small mw-scroll-hint">Fais défiler la grille horizontalement si toutes les colonnes ne sont pas visibles.</p>}
   {game.phase==='lobby'?<section className="mw-panel mw-lobby"><h2>Prépare ton exploration</h2><p>Une grille à résoudre seul ou ensemble. Le chronomètre démarre au premier clic.</p>
    {canControl&&<div className="mw-settings"><label>Difficulté<select value={game.settings.difficulty} disabled={!connected} onChange={e=>action('settings',{field:'difficulty',value:e.target.value})}>{Object.entries(LEVELS).map(([k,v])=><option key={k} value={k}>{v} · {k==='easy'?'9 × 9, 10 mines':k==='medium'?'16 × 16, 40 mines':'30 × 16, 99 mines'}</option>)}</select></label><label>Mode<select value={game.settings.mode} disabled={!connected} onChange={e=>action('settings',{field:'mode',value:e.target.value})}><option value="coop">Coopératif · jusqu’à 8</option><option value="solo" disabled={game.seats.length>1}>Solo · 1 joueur</option></select></label></div>}
    <div className="mw-actions">{!me?<button className="mw-primary" disabled={!connected||game.seats.length>=(game.settings.mode==='solo'?1:8)} onClick={()=>action('join')}><Users size={16}/> {game.settings.mode==='solo'?'Prendre la place':'Participer'}</button>:<button disabled={!connected} onClick={()=>action('leave')}>Libérer ma place</button>}{canControl&&<button className="mw-primary" disabled={!connected||!game.seats.length} onClick={()=>action('start')}>Lancer la partie <Check size={16}/></button>}</div>
    {!canControl&&<p className="mw-small">L’hôte choisit les réglages et lance la partie.</p>}
   </section>:finished?<section className={'mw-panel mw-result'+(won?' mw-result-win':'')}><small>{won?'BELLE EXPLORATION':'UNE NOUVELLE CHANCE ?'}</small><h2>{won?'La grille est libérée !':game.result?.reason==='abandoned'?'Partie terminée':'Une mine… mais pas la fin du monde.'}</h2><p>{game.opened} cases sûres découvertes · {clock(game.elapsed)}</p>{canControl?<div className="mw-actions"><button className="mw-primary" disabled={!connected||!game.seats.some(s=>s.connected)} onClick={()=>action('restart')}><RotateCcw size={16}/> Nouvelle grille</button><button disabled={!connected} onClick={()=>action('reset')}>Changer les réglages</button></div>:<p className="mw-small">L’hôte peut lancer une nouvelle grille.</p>}</section>:
    <section className="mw-panel mw-controls"><div className="mw-tools"><button aria-pressed={!flagMode} className={!flagMode?'mw-selected':''} disabled={!playable} onClick={()=>setFlagMode(false)}><MousePointer2 size={17}/> Découvrir</button><button aria-pressed={flagMode} className={flagMode?'mw-selected':''} disabled={!playable} onClick={()=>setFlagMode(true)}><Flag size={17}/> Drapeau</button></div><p>{flagMode?'Clique une case fermée pour poser ou retirer un drapeau.':'Clique une case pour la découvrir. Clic droit ou touche F pour poser un drapeau.'}</p>{!me&&game.settings.mode==='coop'&&<button className="mw-primary" disabled={!connected||game.seats.length>=8} onClick={()=>action('join')}>Rejoindre l’équipe</button>}</section>}
  </section><aside className="mw-side">
   <section className="mw-panel"><h2><Users size={18}/> {game.settings.mode==='solo'?'À la table':'L’équipe'}</h2><p className="mw-small">{game.spectators} spectateur{game.spectators>1?'s':''}</p><ol className="mw-players">{game.seats.map((s,i)=><li key={s.id}><span className={'mw-avatar mw-avatar-'+i%4}>{s.name.slice(0,1).toUpperCase()}</span><div><strong>{s.name}{s.id===userId?' (toi)':''}</strong><small>{s.connected?(game.phase==='lobby'?'Prêt à explorer':`${s.opened} cases découvertes`):'Déconnecté'}</small></div><span className={s.connected?'mw-online':'mw-offline'} aria-label={s.connected?'Connecté':'Déconnecté'}/></li>)}</ol>{!game.seats.length&&<p className="mw-small">La grille attend ses explorateurs.</p>}</section>
   <section className="mw-panel"><h2><ShieldCheck size={18}/> Votre progression</h2><div className="mw-progress-label"><strong>{Math.round(game.opened/game.safe_total*100)} %</strong><span>{game.opened} / {game.safe_total}</span></div><progress max={game.safe_total} value={game.opened} aria-label="Cases sûres découvertes"/><p className="mw-small">Découvrez toutes les cases sans mine pour gagner. Il n’est pas nécessaire de poser tous les drapeaux.</p></section>
   <details className="mw-panel mw-rules"><summary>Comment jouer ?</summary><p>Un chiffre indique le nombre de mines dans les huit cases autour. Une case vide ouvre automatiquement une zone sûre.</p><p>Pose un drapeau sur une mine supposée. Si un chiffre a autant de drapeaux voisins que sa valeur, clique-le pour découvrir les autres voisins. Attention : un mauvais drapeau peut faire perdre la partie.</p><p>Au clavier : flèches pour naviguer, Entrée pour découvrir, F ou Espace pour poser un drapeau. Sur mobile, utilise le bouton Drapeau.</p><p>Le premier clic et ses voisins sont protégés. Ensuite, des choix peuvent parfois être nécessaires : la grille n’est pas garantie sans devinette.</p><p>En coopération, chacun peut découvrir et marquer les cases. Si tout le monde quitte la table, la partie se met en pause jusqu’à 2 minutes. Elle reprend au retour d’un joueur.</p></details>
   <div className="mw-footer">✦ Un indice après l’autre.</div>
  </aside></div>
  {confirm&&<div className="mw-overlay"><section role="dialog" aria-modal="true" aria-label="Fermer la partie" className="mw-panel mw-dialog"><h2>Quitter cette grille ?</h2><p>Le retour au menu fermera cette partie pour tout le monde.</p><div className="mw-actions"><button ref={cancel} onClick={()=>setConfirm(false)}>Rester</button><button ref={trigger} className="mw-primary" onClick={()=>{send({type:'choose_game',game:'menu'});setConfirm(false);}}>Retour au menu</button></div></section></div>}
 </main>;
}
