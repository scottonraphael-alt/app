import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,BookOpen,Flag,RotateCcw,Timer,Trophy,Users,Volume2,VolumeX} from 'lucide-react';
import {useBoardSounds} from './useBoardSounds';
import './UnoGame.css';

const COLORS={red:{label:'Rouge',symbol:'♥'},yellow:{label:'Jaune',symbol:'☀'},green:{label:'Vert',symbol:'♣'},blue:{label:'Bleu',symbol:'◆'}};
const NAMES={skip:'Saut de tour',reverse:'Changement de sens',draw2:'+2',wild:'Joker',wild4:'Joker +4'};
const MARKS={skip:'⊘',reverse:'⇄',draw2:'+2',wild:'✦',wild4:'+4'};
export function cardName(card){return `${card.color?COLORS[card.color].label+' ':''}${NAMES[card.value]||card.value}`;}
export function UnoCard({card,back=false}){
 if(back)return <span className="un-card un-back" aria-hidden="true"><span>✦</span><b>OASIS</b><small>À VOUS DE JOUER</small></span>;
 return <span className={'un-card un-'+(card.color||'wild')} aria-hidden="true"><small className="un-card-corner">{MARKS[card.value]||card.value}</small><span className="un-card-center">{MARKS[card.value]||card.value}</span><span className="un-card-color">{card.color?COLORS[card.color].symbol+' '+COLORS[card.color].label:'JOKER'}</span><small className="un-card-corner un-bottom">{MARKS[card.value]||card.value}</small></span>;
}

export default function UnoGame({state,userId,canControl,connected,send,error,onInvite}){
 const game=state.uno;
 const [now,setNow]=useState(performance.now()),[modal,setModal]=useState(null),[wild,setWild]=useState(null);
 const dialog=useRef(null);
 const me=game.seats.find(s=>s.id===userId),active=game.seats[game.turn-1];
 const playing=game.phase==='playing',finished=game.phase==='finished';
 const hand=game.hand||[];
 const playable=connected&&playing&&!game.paused&&Boolean(me)&&!me.retired;
 const ownTurn=playable&&active?.id===userId;
 const sounds=useBoardSounds('uno',game.round_id,game.revision,connected);
 const remaining=game.remaining===null?null:Math.max(0,Math.ceil(game.remaining-(game.paused?0:(now-state.at)/1000)));
 useEffect(()=>{if(!playing||game.paused)return undefined;const id=setInterval(()=>setNow(performance.now()),250);return()=>clearInterval(id);},[playing,game.paused]);
 useEffect(()=>{setModal(null);setWild(null);},[game.round_id,game.turn,game.phase,connected]);
 useEffect(()=>{
  if(!modal)return undefined;
  const previous=document.activeElement;dialog.current?.querySelector('button')?.focus();
  const listener=e=>{
   if(e.key==='Escape'){setModal(null);setWild(null);}
   if(e.key!=='Tab')return;
   const buttons=[...dialog.current.querySelectorAll('button:not(:disabled)')],first=buttons[0],last=buttons.at(-1);
   if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
   else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
  };
  document.addEventListener('keydown',listener);return()=>{document.removeEventListener('keydown',listener);previous?.focus();};
 },[modal]);
 function action(kind,extra={}){sounds.unlock();send({type:'uno_'+kind,round_id:game.round_id,revision:game.revision,...extra});}
 function play(card){
  if(!ownTurn||!(game.playable_ids||[]).includes(card.id))return;
  if(card.color===null){setWild(card.id);setModal('wild');}
  else action('play',{card_id:card.id});
 }
 function name(uid){return game.seats.find(s=>s.id===uid)?.name||'Un joueur';}
 function historyText(event){
  const who=name(event.player_id);
  return {play:`${who} · ${event.card?cardName(event.card):''}${event.card?.color===null?' → '+COLORS[event.color]?.label:''}`,
   draw:`${who} pioche ${event.count||0} carte(s)`,penalty:`${who} prend ${event.count} cartes`,pass:`${who} garde sa carte`,
   uno:`${who} annonce UNO !`,caught:`${who} signale l’oubli de ${name(event.target_id)} · +2`,
   challenge_won:`${who} gagne sa contestation · ${name(event.target_id)} prend 4 cartes`,challenge_lost:`${who} perd sa contestation · +6`,
   accept_four:`${who} accepte le +4`,timeout:`Temps écoulé pour ${who}`,resign:`${who} abandonne`,disconnect:`${who} n’est pas revenu`}[event.kind]||who;
 }
 const winner=game.result?.winner_id;
 const status=!connected?'Reconnexion à OasisGame…':game.phase==='lobby'?'Installez-vous à la table. La première manche vous attend.':game.paused?'Partie en pause · reconnexion d’un joueur (2 minutes maximum)':finished?(winner?`${name(winner)} remporte la manche !`:'La manche est terminée.'):game.pending?`${name(game.pending.target)} doit accepter ou contester le +4.`:ownTurn?(game.can_pass?'Carte piochée : joue-la ou garde-la.':'À toi de jouer !'):me?.retired?'Tu suis la manche en spectateur.':`Au tour de ${active?.name||'…'}`;
 return <main className="un-page">
  <header className="un-header"><span className="og-brand">✦ OasisGame</span><div><button aria-label={sounds.enabled?'Couper les sons':'Activer les sons'} onClick={sounds.toggle}>{sounds.enabled?<Volume2 size={17}/>:<VolumeX size={17}/>}</button><button onClick={()=>setModal('rules')}><BookOpen size={16}/> Règles</button>{onInvite&&game.phase==='lobby'&&<button onClick={onInvite}><Users size={16}/> Inviter</button>}{canControl&&<button disabled={!connected} onClick={()=>playing?setModal('menu'):send({type:'choose_game',game:'menu'})}><ArrowLeft size={16}/> Tous les jeux</button>}</div></header>
  <div className="un-heading"><div><small>TOUTES LES COULEURS, TOUS LES REBONDISSEMENTS</small><h1>UNO<span>Une dernière carte. Et tout peut changer.</span></h1></div><span><Users size={16}/> {game.seats.length}/8 joueurs · Manche {game.round||1}</span></div>
  {error&&<p className="og-error" role="alert">{error}</p>}
  <div className={'un-status'+(ownTurn?' un-own':'')} role="status"><span>✦</span>{status}{playing&&remaining!==null&&<strong><Timer size={16}/>{Math.floor(remaining/60)}:{String(remaining%60).padStart(2,'0')}</strong>}</div>
  <div className="un-layout"><section className="un-stage">
   <div className="un-opponents" aria-label="Autres joueurs">{game.seats.filter(s=>s.id!==userId).map(s=><div key={s.id} className={'un-opponent'+(playing&&s.id===active?.id?' un-current':'')+(s.retired?' un-retired':'')}><div className="un-mini-stack"><span/><span/><span/></div><strong>{s.name}</strong><small>{s.retired?'Abandon':!s.connected?'Déconnecté':`${s.cards} carte${s.cards>1?'s':''}`}</small>{s.uno&&s.cards===1&&<b className="un-uno-badge">UNO !</b>}</div>)}</div>
   <div className={'un-table un-table-'+(game.color||'neutral')}>
    <div className="un-table-top"><span>{game.direction===1?'↻':'↺'} {game.direction===1?'Sens horaire':'Sens inverse'}</span>{game.color&&<span className={'un-color-pill un-'+game.color}>{COLORS[game.color].symbol} Couleur : {COLORS[game.color].label}</span>}</div>
    <div className="un-piles"><div className="un-pile"><button className="un-draw-pile" aria-label="Piocher une carte" disabled={!connected||!game.can_draw} onClick={()=>action('draw')}><UnoCard back/></button><span>Pioche · {game.deck_count} cartes</span></div><div className="un-pile un-discard">{game.top?<UnoCard card={game.top}/>:<div className="un-empty-card">✦</div>}<span>Carte à suivre</span></div></div>
    <p className="un-table-note">{game.phase==='lobby'?'Sept cartes chacun. Une seule à garder pour la fin.':ownTurn?'Même couleur, même chiffre ou même symbole.':playing?'Les mains restent privées. Les surprises aussi.':'Une nouvelle manche, une nouvelle chance.'}</p>
   </div>
   {game.phase==='lobby'?<section className="un-panel un-lobby"><h2>Une place pour toi ?</h2><p>De 2 à 8 joueurs. Le premier qui n’a plus de cartes remporte la manche.</p><div className="un-actions">{!me?<button className="un-primary" disabled={!connected||game.seats.length>=8} onClick={()=>action('join')}>Prendre une place</button>:<button disabled={!connected} onClick={()=>action('leave')}>Libérer ma place</button>}{canControl&&<><label>Temps par tour<select value={game.settings.seconds} disabled={!connected} onChange={e=>action('settings',{field:'seconds',value:Number(e.target.value)})}>{[[0,'Sans limite'],[30,'30 secondes'],[60,'1 minute'],[120,'2 minutes']].map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label><button className="un-primary" disabled={!connected||game.seats.length<2} onClick={()=>action('start')}>Distribuer les cartes <ArrowRight size={16}/></button></>}</div>{!canControl&&<p className="un-muted">L’hôte lance la manche lorsque tout le monde est installé.</p>}</section>:
    finished?<section className="un-panel un-result"><Trophy size={30}/><small>FIN DE MANCHE</small><h2>{winner?`${name(winner)} remporte la manche !`:'Manche interrompue'}</h2><p>{winner?`+ ${game.result.points} points grâce aux cartes restantes des adversaires.`:game.result?.reason==='blocked'?'La pioche est vide et personne ne peut jouer.':'Les joueurs ont quitté la partie.'}</p>{canControl?<div className="un-actions"><button className="un-primary" disabled={!connected||game.seats.filter(s=>s.connected).length<2} onClick={()=>action('restart')}><RotateCcw size={16}/> Rejouer ensemble</button><button disabled={!connected} onClick={()=>action('reset')}>Nouvelle table</button></div>:<p className="un-muted">L’hôte peut relancer une manche.</p>}</section>:
    <section className="un-panel un-hand"><div className="un-hand-heading"><strong>{me&&!me.retired?'Ta main':'Mode spectateur'}</strong><small>{me&&!me.retired?`${hand.length} carte${hand.length>1?'s':''} · visibles uniquement par toi`:'Les cartes des joueurs restent cachées.'}</small></div>
     <div className="un-hand-cards" role="group" aria-label="Tes cartes">{hand.map(card=><button key={card.id} className={'un-hand-card'+(ownTurn&&game.playable_ids?.includes(card.id)?' un-can-play':'')} disabled={!ownTurn||!game.playable_ids?.includes(card.id)} aria-label={'Jouer '+cardName(card)} onClick={()=>play(card)}><UnoCard card={card}/></button>)}</div>
     {game.can_challenge&&connected&&<div className="un-challenge"><h3>Un +4 vient de tomber.</h3><p>Tu peux piocher 4 cartes et passer, ou contester si tu penses que {name(game.pending.from)} avait la couleur demandée. Une contestation perdue coûte 6 cartes.</p><div className="un-actions"><button onClick={()=>action('accept')}>Piocher 4 et passer</button><button className="un-primary" onClick={()=>action('challenge')}>Contester le +4</button></div></div>}
     <div className="un-actions"><button disabled={!connected||!game.can_draw} onClick={()=>action('draw')}>Piocher une carte</button>{game.can_pass&&<button disabled={!connected} onClick={()=>action('pass')}>Garder la carte et passer</button>}<button className="un-call" disabled={!connected||!game.can_uno} onClick={()=>action('uno')}>UNO !</button>{game.can_catch&&<button className="un-catch" disabled={!connected} onClick={()=>action('catch')}>UNO oublié ! (+2)</button>}</div>
     {hand.length===2&&game.can_uno&&<p className="un-uno-hint">Pense à annoncer UNO avant de poser ton avant-dernière carte.</p>}
     {me&&!me.retired&&<div className="un-hand-footer"><span>Un joker te laisse choisir la couleur.</span><button disabled={!connected} onClick={()=>setModal('resign')}><Flag size={13}/> Abandonner</button></div>}
    </section>}
  </section><aside className="un-side"><section className="un-panel"><h2><Users size={17}/> La table</h2><p className="un-muted">{game.spectators} spectateur{game.spectators>1?'s':''}</p><ol className="un-players">{game.seats.map((s,i)=><li key={s.id} className={(playing&&s.id===active?.id?'un-current ':'')+(s.retired?'un-retired':'')}><span className={'un-avatar un-avatar-'+i%4}>{s.name.slice(0,1).toUpperCase()}</span><div><strong>{s.name}{s.id===userId?' (toi)':''}</strong><small>{s.retired?'Abandon':!s.connected?'Déconnecté':game.phase==='lobby'?'À table':`${s.cards} carte${s.cards>1?'s':''}`}{s.uno&&s.cards===1?' · UNO !':''}</small></div><b>{s.score}<small>pts</small></b></li>)}</ol>{!game.seats.length&&<p className="un-muted">Les cartes attendent leurs joueurs.</p>}</section>
   <section className="un-panel"><h2>Les derniers coups</h2><ol className="un-history">{[...game.history].reverse().slice(0,8).map(event=><li key={event.id}>{historyText(event)}</li>)}</ol>{!game.history.length&&<p className="un-muted">À vous d’écrire la première manche.</p>}</section><p className="un-footer">✦ Garde une carte, partage le moment.</p></aside></div>
  {modal&&<div className="un-overlay"><section ref={dialog} className="un-panel un-dialog" role="dialog" aria-modal="true" aria-label={modal==='wild'?'Choisir une couleur':modal==='rules'?'Règles de la table':'Confirmer l’action'}>
   {modal==='wild'?<><small>À TOI DE CHANGER LA DONNE</small><h2>Quelle couleur pour la suite ?</h2><div className="un-color-choices">{Object.entries(COLORS).map(([color,data])=><button key={color} className={'un-'+color} onClick={()=>{action('play',{card_id:wild,color});setModal(null);setWild(null);}}>{data.symbol} {data.label}</button>)}</div><button onClick={()=>{setModal(null);setWild(null);}}>Annuler</button></>:
    modal==='rules'?<><small>LES RÈGLES DE LA TABLE</small><h2>Une couleur. Un chiffre. Un rebondissement.</h2><p>Chacun reçoit 7 cartes. Pose la même couleur, le même chiffre ou le même symbole que la carte du centre, ou joue un joker. La première carte est toujours numérotée. Le premier sans carte gagne.</p><p><b>⊘ Saut :</b> le suivant passe. <b>⇄ Inversion :</b> le sens change ; à deux joueurs, tu rejoues. <b>+2 :</b> le suivant pioche 2 cartes et passe. Les +2 et +4 ne se cumulent pas.</p><p><b>Joker :</b> choisis la couleur. <b>+4 :</b> le suivant peut accepter ou contester. S’il prouve grâce au serveur que tu avais encore la couleur précédente, tu pioches 4 cartes et il garde son tour. Sinon il pioche 6 et passe. Aucun contenu de main n’est révélé aux autres.</p><p>Tu peux piocher même si tu peux jouer. Si la carte piochée convient, joue-la ou garde-la et passe. Tu ne peux pas poser une autre carte après avoir pioché.</p><p>Annonce <b>UNO !</b> avant de poser ton avant-dernière carte. Si tu oublies, un adversaire peut te faire piocher 2 cartes avant le prochain coup. Tu peux te rattraper en annonçant UNO avant d’être signalé.</p><p>Les chiffres valent leur nombre, les actions 20 points, les jokers 50. Le gagnant reçoit les points des mains adverses ; les totaux se conservent entre les revanches. Le chrono est facultatif : à expiration, le tour passe avec une carte piochée si tu n’as pas déjà pioché, ou le +4 en attente est accepté.</p><p>Une déconnexion met la manche en pause pendant 2 minutes. Au-delà, le joueur abandonne et les autres continuent. À deux, le joueur restant gagne.</p><button className="un-primary" onClick={()=>setModal(null)}>C’est parti !</button></>:
    <><h2>{modal==='menu'?'Fermer cette table ?':'Abandonner cette manche ?'}</h2><p>{modal==='menu'?'Le retour au menu arrête la manche pour tout le monde.':'Tu pourras regarder la suite, mais tes cartes ne seront plus jouables.'}</p><div className="un-actions"><button onClick={()=>setModal(null)}>Rester</button><button className="un-primary" onClick={()=>{if(modal==='menu')send({type:'choose_game',game:'menu'});else action('resign');setModal(null);}}>Confirmer</button></div></>}
  </section></div>}
 </main>;
}
