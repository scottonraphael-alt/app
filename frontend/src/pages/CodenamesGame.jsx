import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,BookOpen,Check,Eye,EyeOff,Flag,RotateCcw,Shield,Timer,Trophy,Users,Volume2,VolumeX} from 'lucide-react';
import {useBoardSounds} from './useBoardSounds';
import './CodenamesGame.css';

const TEAMS={red:'Rouge',blue:'Bleue'},KINDS={red:'Agent rouge',blue:'Agent bleu',neutral:'Neutre',assassin:'Assassin'};
const countLabel=count=>count==='infinity'?'∞':count;

export default function CodenamesGame({state,userId,canControl,connected,send,error,onInvite}){
 const game=state.codenames;
 const [word,setWord]=useState(''),[count,setCount]=useState('2'),[hideKey,setHideKey]=useState(false);
 const [modal,setModal]=useState(null),[candidate,setCandidate]=useState(null),[focused,setFocused]=useState(0);
 const [now,setNow]=useState(performance.now());
 const dialog=useRef(null);
 const lobby=game.phase==='lobby',playing=game.phase==='playing',finished=game.phase==='finished';
 const master=game.own_role==='spymaster',showKey=master&&!hideKey&&Array.isArray(game.key);
 const own=game.seats.find(s=>s.id===userId),playable=connected&&game.can_guess;
 const sounds=useBoardSounds('codenames',game.round_id,game.revision,connected);
 const remaining=game.remaining_time===null?null:Math.max(0,Math.ceil(game.remaining_time-(game.paused?0:(now-state.at)/1000)));
 const candidateRevealed=candidate!==null&&game.board[candidate]?.revealed;
 useEffect(()=>{setModal(null);setCandidate(null);setWord('');},[game.round_id,game.turn,game.stage,game.phase,connected,candidateRevealed]);
 useEffect(()=>{setHideKey(false);setFocused(0);},[game.round_id]);
 useEffect(()=>{if(!playing||game.paused)return undefined;const id=setInterval(()=>setNow(performance.now()),250);return()=>clearInterval(id);},[playing,game.paused]);
 useEffect(()=>{
  if(!modal)return undefined;
  const previous=document.activeElement;dialog.current?.querySelector('button')?.focus();
  const keydown=e=>{
   if(e.key==='Escape'){setModal(null);setCandidate(null);}
   if(e.key!=='Tab')return;
   const buttons=[...dialog.current.querySelectorAll('button:not(:disabled)')],first=buttons[0],last=buttons.at(-1);
   if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
   else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
  };
  document.addEventListener('keydown',keydown);return()=>{document.removeEventListener('keydown',keydown);previous?.focus();};
 },[modal]);
 function action(kind,extra={}){sounds.unlock();send({type:'cn_'+kind,round_id:game.round_id,revision:game.revision,...extra});}
 function join(team,role){action('join',{team,role});}
 function navigate(event){
  const cell=Number(event.target.dataset.cell),delta={ArrowLeft:-1,ArrowRight:1,ArrowUp:-5,ArrowDown:5}[event.key];
  if(!Number.isInteger(cell)||!delta)return;
  event.preventDefault();const next=Math.max(0,Math.min(24,cell+delta));event.currentTarget.querySelector(`[data-cell="${next}"]`)?.focus();
 }
 function historyText(event){
  const name=game.seats.find(s=>s.id===event.player_id)?.name||'';
  if(event.kind==='clue')return `${TEAMS[event.team]} · ${event.word} ${countLabel(event.count)}`;
  if(event.kind==='guess')return `${name} révèle ${event.word} · ${KINDS[event.color]}`;
  return event.kind==='timeout'?`${TEAMS[event.team]} · Temps écoulé`:`${TEAMS[event.team]} · Fin du tour`;
 }
 const status=!connected?'Reconnexion à OasisGame…':lobby?'Choisissez votre équipe et votre rôle.':game.paused?'Mission en pause · un rôle indispensable attend une reconnexion (2 minutes).':finished?(game.result?.winner?`L’équipe ${TEAMS[game.result.winner].toLowerCase()} remporte la mission !`:'La mission est terminée.'):
  game.stage==='clue'?`L’équipe ${TEAMS[game.turn].toLowerCase()} prépare son indice.`:`Les agents de l’équipe ${TEAMS[game.turn].toLowerCase()} sont en mission.`;
 return <main className="cn-page">
  <header className="cn-header"><span className="og-brand">✦ OasisGame</span><div><button aria-label={sounds.enabled?'Couper les sons':'Activer les sons'} onClick={sounds.toggle}>{sounds.enabled?<Volume2 size={17}/>:<VolumeX size={17}/>}</button><button onClick={()=>setModal('rules')}><BookOpen size={16}/> Règles</button>{onInvite&&lobby&&<button onClick={onInvite}><Users size={16}/> Inviter</button>}{canControl&&<button disabled={!connected} onClick={()=>playing?setModal('menu'):send({type:'choose_game',game:'menu'})}><ArrowLeft size={16}/> Tous les jeux</button>}</div></header>
  <div className="cn-heading"><div><small>UN INDICE. PLUSIEURS PISTES. UNE SEULE ÉQUIPE.</small><h1>Codenames</h1><p>Les bons mots font les meilleures connexions.</p></div><span><Users size={16}/> {game.seats.length}/16 joueurs · Français</span></div>
  {error&&<p className="og-error" role="alert">{error}</p>}
  <div className={'cn-status cn-turn-'+game.turn} role="status"><span>◇</span>{status}{remaining!==null&&playing&&<strong><Timer size={16}/>{Math.floor(remaining/60)}:{String(remaining%60).padStart(2,'0')}</strong>}</div>
  <div className="cn-layout"><section className="cn-stage">
   <div className="cn-scoreboard">{Object.entries(TEAMS).map(([team,label])=><div key={team} className={'cn-team-score cn-'+team+(playing&&game.turn===team?' cn-active':'')}><span><Shield size={17}/> Équipe {label.toLowerCase()}</span><strong>{lobby?'—':game.remaining_agents[team]}<small>{lobby?'à constituer':'agents à trouver'}</small></strong><span className="cn-series">{game.scores[team]} mission{game.scores[team]>1?'s':''} gagnée{game.scores[team]>1?'s':''}</span></div>)}</div>
   {master&&playing&&<div className="cn-private"><span><Eye size={16}/> Clé privée de maître-espion · évite de partager ton écran.</span><button onClick={()=>setHideKey(!hideKey)}>{hideKey?<Eye size={15}/>:<EyeOff size={15}/>} {hideKey?'Afficher la clé':'Masquer la clé'}</button></div>}
   <div className="cn-board" role="group" aria-label="Grille de 25 mots" onKeyDown={navigate}>
    {(lobby?Array.from({length:25},()=>({word:'OASIS',revealed:false,color:null})):game.board).map((card,index)=>{
     const color=card.color||(showKey?game.key[index]:null),selected=game.selected===index;
     return <button type="button" key={index} data-cell={index} tabIndex={focused===index?0:-1} onFocus={()=>setFocused(index)}
      className={`cn-cell cn-card-${color||'hidden'}${card.revealed?' cn-revealed':''}${showKey&&!card.revealed?' cn-secret':''}${selected?' cn-selected':''}${lobby?' cn-placeholder':''}`}
      style={{'--cn-length':Math.max(4,card.word.length)}} disabled={!playable||card.revealed||lobby}
      aria-label={card.word+(color?' · '+KINDS[color]:'')+(card.revealed?' · déjà révélé':'')}
      onClick={()=>{setCandidate(index);setModal('guess');}}>
       <span className="cn-card-word">{card.word}</span>{color&&<small className="cn-affiliation">{KINDS[color]}</small>}
       {card.revealed&&<Check className="cn-revealed-mark" size={14} aria-hidden="true"/>}
       {game.votes[index]>0&&!card.revealed&&<span className="cn-votes" aria-label={`${game.votes[index]} proposition(s)`}><Users size={10}/>{game.votes[index]}</span>}
     </button>;
    })}
   </div>
   {lobby?<section className="cn-panel cn-setup"><h2>La mission commence avec vous.</h2><p>Il faut un maître-espion et au moins un agent dans chaque équipe. Les rôles restent fixes pendant la manche pour protéger la clé secrète.</p>{canControl&&<div className="cn-settings"><label>Temps par phase<select disabled={!connected} value={game.settings.seconds} onChange={e=>action('settings',{field:'seconds',value:Number(e.target.value)})}>{[[0,'Sans limite'],[60,'1 minute'],[120,'2 minutes'],[180,'3 minutes'],[300,'5 minutes']].map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label><label>Première équipe<select disabled={!connected} value={game.settings.starting} onChange={e=>action('settings',{field:'starting',value:e.target.value})}><option value="random">Au hasard</option><option value="red">Rouge</option><option value="blue">Bleue</option></select></label><button className="cn-primary" disabled={!connected||!game.ready} onClick={()=>action('start')}>Lancer la mission <Check size={16}/></button></div>}{own&&<button disabled={!connected} onClick={()=>action('leave')}>Revenir en spectateur</button>}{!game.ready&&<p className="cn-muted">Constituez les deux équipes dans les panneaux à droite.</p>}</section>:
    finished?<section className="cn-panel cn-result"><Trophy size={28}/><small>FIN DE MISSION</small><h2>{game.result?.winner?`Victoire de l’équipe ${TEAMS[game.result.winner].toLowerCase()} !`:'Mission interrompue'}</h2><p>{game.result?.reason==='assassin'?'L’assassin a été découvert.':game.result?.reason==='agents_found'?'Tous les agents de l’équipe gagnante ont été retrouvés.':'Un rôle indispensable n’a pas pu revenir à la table.'} La clé complète est maintenant visible.</p>{canControl?<div className="cn-actions"><button className="cn-primary" disabled={!connected||!Object.entries(TEAMS).every(([team])=>['agent','spymaster'].every(role=>game.seats.some(s=>s.team===team&&s.role===role&&s.connected)))} onClick={()=>action('restart')}><RotateCcw size={16}/> Nouvelle mission</button><button disabled={!connected} onClick={()=>action('reset')}>Recomposer les équipes</button></div>:<p className="cn-muted">L’hôte peut relancer une mission.</p>}</section>:
    <section className={'cn-panel cn-clue-panel cn-turn-'+game.turn}>
     {game.can_clue?<><small>À TOI, MAÎTRE-ESPION</small><h2>Un mot pour les relier.</h2><form onSubmit={e=>{e.preventDefault();if(connected&&word.trim())action('clue',{word:word.trim(),count:count==='infinity'?count:Number(count)});}}><label>Ton indice<input value={word} maxLength={30} placeholder="Un seul mot…" autoComplete="off" onChange={e=>setWord(e.target.value)}/></label><label>Nombre de mots<select value={count} onChange={e=>setCount(e.target.value)}>{[1,2,3,4,5,6,7,8,9,0,'infinity'].map(n=><option key={n} value={n}>{countLabel(n)}</option>)}</select></label><button className="cn-primary" disabled={!connected||!word.trim()}>Donner l’indice</button></form><p className="cn-muted">Pas de mot encore caché sur la grille, ni de variante évidente. Tes agents feront le lien.</p></>:
      game.clue?<><small>LE MESSAGE DU MAÎTRE-ESPION</small><div className="cn-current-clue"><strong>{game.clue.word}</strong><span>{countLabel(game.clue.count)}</span></div><p>{game.guesses_left===null?'Nombre de tentatives illimité pour cet indice.':`${game.guesses_left} tentative${game.guesses_left>1?'s':''} restante${game.guesses_left>1?'s':''}, bonus compris.`}</p>{game.own_team===game.turn&&game.own_role==='agent'&&<div className="cn-actions"><button disabled={!connected||!game.can_end} onClick={()=>setModal('end')}><Flag size={15}/> Terminer le tour</button>{game.selected!==null&&<button disabled={!playable} onClick={()=>action('vote',{cell:null})}>Retirer ma proposition</button>}</div>}<p className="cn-muted">{game.can_guess?'Clique un mot pour le proposer ou confirmer sa révélation.':'Seuls les agents de l’équipe qui joue peuvent révéler les mots.'}</p></>:
      <><small>LE PROCHAIN INDICE ARRIVE</small><h2>Un peu de mystère…</h2><p>Le maître-espion de l’équipe {TEAMS[game.turn].toLowerCase()} prépare un mot et un nombre. Les agents pourront ensuite faire leurs propositions.</p></>}
    </section>}
   <div className="cn-legend"><span className="cn-red">Agent rouge</span><span className="cn-blue">Agent bleu</span><span className="cn-neutral">Neutre</span><span className="cn-assassin">Assassin : défaite immédiate</span></div>
  </section><aside className="cn-side">
   {Object.entries(TEAMS).map(([team,label])=>{const members=game.seats.filter(s=>s.team===team),spy=members.find(s=>s.role==='spymaster');return <section key={team} className={'cn-panel cn-team-panel cn-team-'+team}><h2><Shield size={18}/> Équipe {label.toLowerCase()}</h2><p className="cn-muted">{members.length}/8 membres · {game.own_team===team?'ton équipe':lobby?'une place pour toi ?':''}</p><ul className="cn-members">{members.map(s=><li key={s.id}><span className={'cn-avatar cn-'+team}>{s.name.slice(0,1).toUpperCase()}</span><div><strong>{s.name}{s.id===userId?' (toi)':''}</strong><small>{s.role==='spymaster'?'Maître-espion':'Agent'}{!s.connected?' · déconnecté':''}</small></div>{s.role==='spymaster'&&<Eye size={14}/>}</li>)}</ul>{!members.length&&<p className="cn-muted">Cette équipe cherche ses premiers agents.</p>}{lobby&&<div className="cn-join"><button disabled={!connected||(members.length>=8&&own?.team!==team)} onClick={()=>join(team,'agent')}><Users size={15}/> Rejoindre les agents {team==='red'?'rouges':'bleus'}</button><button disabled={!connected||(spy&&spy.id!==userId)||(members.length>=8&&own?.team!==team)} onClick={()=>join(team,'spymaster')}><Eye size={15}/> {spy&&spy.id!==userId?'Maître-espion en place':`Devenir maître-espion ${team==='red'?'rouge':'bleu'}`}</button></div>}</section>;})}
   <section className="cn-panel"><h2>Le carnet de mission</h2><ol className="cn-history">{[...game.history].reverse().slice(0,10).map(event=><li key={event.id} className={'cn-log-'+event.team}>{historyText(event)}</li>)}</ol>{!game.history.length&&<p className="cn-muted">Les premiers indices restent à écrire.</p>}</section><p className="cn-footer">{game.spectators} spectateur{game.spectators>1?'s':''} · ✦ Faites confiance aux connexions.</p>
  </aside></div>
  {modal&&<div className="cn-overlay"><section ref={dialog} className="cn-panel cn-dialog" role="dialog" aria-modal="true" aria-label={modal==='rules'?'Règles de Codenames':modal==='guess'?'Choisir ce mot':'Confirmer l’action'}>
   {modal==='guess'&&candidate!==null?<><small>À TON ÉQUIPE DE DÉCIDER</small><h2>{game.board[candidate]?.word}</h2><p>Une proposition aide tes coéquipiers à se repérer. Une révélation engage toute l’équipe et ne peut pas être annulée.</p><div className="cn-actions"><button disabled={!playable} onClick={()=>{action('vote',{cell:game.selected===candidate?null:candidate});setModal(null);}}>{game.selected===candidate?'Retirer ma proposition':'Proposer à l’équipe'}</button><button className="cn-primary" disabled={!playable||game.board[candidate]?.revealed} onClick={()=>{action('guess',{cell:candidate});setModal(null);setCandidate(null);}}>Révéler pour l’équipe</button><button onClick={()=>{setModal(null);setCandidate(null);}}>Annuler</button></div></>:
    modal==='rules'?<><small>LES RÈGLES DE LA MISSION</small><h2>Reliez les mots. Évitez les fausses pistes.</h2><p>Deux équipes, chacune avec un maître-espion et au moins un agent. Les maîtres-espions voient la clé privée : l’équipe qui commence a 9 agents, l’autre 8. Il y a aussi 7 mots neutres et 1 assassin.</p><p>À son tour, le maître-espion donne un seul mot et un nombre. Le mot doit relier les cartes de son équipe, sans reprendre un mot encore caché de la grille ou une variante évidente. Les équipes s’accordent sur les associations et les dérivés acceptables.</p><p>Les agents doivent tenter au moins un mot. Un mot de leur couleur permet de continuer, dans la limite du nombre annoncé plus un essai bonus. Un mot neutre ou adverse termine le tour ; un mot adverse fait aussi avancer l’autre équipe. Les indices 0 et ∞ permettent des essais sans limite.</p><p>Découvrir tous ses agents fait gagner. Révéler l’assassin fait immédiatement perdre. Cliquer une carte ouvre une confirmation ; les propositions ne révèlent rien. Les maîtres-espions ne peuvent pas choisir les mots à la place des agents.</p><p>Les rôles sont verrouillés pendant la manche. En cas de départ, la partie continue si chaque rôle reste représenté ; sinon elle se met en pause pendant 2 minutes. Le chrono, si activé, s’applique séparément à l’indice puis aux essais. À expiration, le tour change.</p><button className="cn-primary" onClick={()=>setModal(null)}>Mission comprise</button></>:
    <><h2>{modal==='menu'?'Fermer cette mission ?':'Terminer votre tour ?'}</h2><p>{modal==='menu'?'Le retour au menu arrête la manche pour tout le monde.':'Les tentatives restantes seront perdues et l’autre équipe préparera son indice.'}</p><div className="cn-actions"><button onClick={()=>setModal(null)}>Annuler</button><button className="cn-primary" onClick={()=>{if(modal==='menu')send({type:'choose_game',game:'menu'});else action('end');setModal(null);}}>Confirmer</button></div></>}
  </section></div>}
 </main>;
}
