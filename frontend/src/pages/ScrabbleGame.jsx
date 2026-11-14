import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, BookOpen, Check, Flag, MessageCircle, RotateCcw, Shuffle, Timer, Users, Volume2, VolumeX } from 'lucide-react';
import { useBoardSounds } from './useBoardSounds';
import './ScrabbleGame.css';

const VALUES = Object.fromEntries([[1,'AEILNORSTU'],[2,'DGM'],[3,'BCP'],[4,'FHV'],[8,'JQ'],[10,'KWXYZ'],[0,'?']].flatMap(([v, letters])=>[...letters].map(l=>[l,v])));
const BONUS = { TW: 'MOT TRIPLE', DW: 'MOT DOUBLE', TL: 'LETTRE TRIPLE', DL: 'LETTRE DOUBLE' };
const REASONS = { empty_rack: 'Le sac est vide et un chevalet a été terminé.', scoreless: 'Six tours consécutifs sans points.', resign: 'Fin de partie après un abandon.', disconnect: 'Délai de reconnexion dépassé.', cancelled: 'Tous les joueurs ont quitté la partie.' };
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
function Tile({letter, blank=false}) {
  return <span className={'sg-tile'+(blank?' sg-blank':'')}><b>{letter==='?'?'◇':letter}</b><small>{blank?0:VALUES[letter]}</small></span>;
}

export default function ScrabbleGame({state,userId,canControl,connected,send,error,onInvite}) {
  const game=state.scrabble;
  const [draft,setDraft]=useState([]), [selected,setSelected]=useState(null), [exchange,setExchange]=useState(false);
  const [swaps,setSwaps]=useState([]), [order,setOrder]=useState([]), [joker,setJoker]=useState(null);
  const [chat,setChat]=useState(''), [confirm,setConfirm]=useState(null), [rules,setRules]=useState(false);
  const [tick,setTick]=useState(0);
  const [focusedCell,setFocusedCell]=useState(112);
  const request=useRef(0), previewRequest=useRef(null), chatBox=useRef(null), dialog=useRef(null);
  const rack=game.rack||[];
  const seat=game.seats.findIndex(s=>s.id===userId)+1;
  const me=game.seats[seat-1];
  const playing=game.phase==='playing';
  const playable=connected&&playing&&seat===game.turn&&!game.paused&&!me?.retired;
  const context=`${game.round_id}:${game.ply}:${rack.join('')}`;
  const sounds=useBoardSounds('scrabble',game.round_id,game.ply,connected);
  const preview=state.scrabble_preview;
  const draftKey=JSON.stringify(draft);
  const validPreview=preview&&preview.request_id===previewRequest.current?.id&&previewRequest.current?.draft===draftKey&&preview.round_id===game.round_id&&preview.ply===game.ply&&draft.length>0;
  const visibleOrder=order.length===rack.length?order:rack.map((_,i)=>i);
  const active=game.seats[game.turn-1];
  const remaining=game.remaining===null?null:Math.max(0,Math.ceil(game.remaining-(game.paused?0:(performance.now()-state.at)/1000)));
  const history=game.history||[];

  useEffect(()=>{
    setDraft([]);setSelected(null);setExchange(false);setSwaps([]);setJoker(null);
    setOrder(rack.map((_,i)=>i));previewRequest.current=null;
    // The authoritative turn revision also clears a draft after timeout or reconnect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[context,connected]);
  useEffect(()=>{const id=setInterval(()=>setTick(v=>v+1),250);return()=>clearInterval(id);},[]);
  useEffect(()=>{if(chatBox.current)chatBox.current.scrollTop=chatBox.current.scrollHeight;},[game.chat?.length]);
  const modalOpen=Boolean(joker||confirm||rules);
  useEffect(()=>{
    if(!modalOpen)return undefined;
    const previous=document.activeElement;
    dialog.current?.querySelector('button')?.focus();
    function keydown(event){
      if(event.key==='Escape'){setJoker(null);setConfirm(null);setRules(false);}
      if(event.key!=='Tab')return;
      const buttons=[...dialog.current.querySelectorAll('button:not(:disabled)')];
      const first=buttons[0],last=buttons.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
    document.addEventListener('keydown',keydown);
    return()=>{document.removeEventListener('keydown',keydown);previous?.focus();};
  },[modalOpen]);
  useEffect(()=>{
    if(!playable||!draft.length){previewRequest.current=null;return undefined;}
    previewRequest.current=null;
    const id=setTimeout(()=>{
      const requestId=++request.current;previewRequest.current={id:requestId,draft:JSON.stringify(draft)};
      send({type:'scr_preview',round_id:game.round_id,ply:game.ply,placements:draft,request_id:requestId});
    },180);
    return()=>clearTimeout(id);
  },[draft,playable,game.round_id,game.ply,send]);
  // tick only drives the local display; the server owns the actual deadline.
  void tick;

  function action(kind,extra={}) {
    sounds.unlock();send({type:'scr_'+kind,round_id:game.round_id,ply:game.ply,...extra});
  }
  function choose(index){
    if(!playable)return;
    sounds.unlock();
    if(exchange){setSwaps(s=>s.includes(index)?s.filter(i=>i!==index):[...s,index]);return;}
    if(draft.some(p=>p.index===index)){setDraft(d=>d.filter(p=>p.index!==index));return;}
    setSelected(selected===index?null:index);
  }
  function place(row,column,dragIndex=selected){
    if(!playable||exchange||game.board[row][column])return;
    if(draft.some(p=>p.row===row&&p.column===column)){
      setDraft(d=>d.filter(p=>p.row!==row||p.column!==column));return;
    }
    if(dragIndex===null||!Number.isInteger(dragIndex)||dragIndex<0||dragIndex>=rack.length||draft.some(p=>p.index===dragIndex))return;
    if(rack[dragIndex]==='?'){setJoker({row,column,index:dragIndex});return;}
    setDraft(d=>[...d,{row,column,index:dragIndex}]);setSelected(null);
  }
  function navigate(event){
    const cell=Number(event.target.dataset.cell);
    const delta={ArrowUp:-15,ArrowDown:15,ArrowLeft:-1,ArrowRight:1}[event.key];
    if(!delta||!Number.isInteger(cell))return;
    event.preventDefault();
    const next=Math.max(0,Math.min(224,cell+delta));
    event.currentTarget.querySelector(`[data-cell="${next}"]`)?.focus();
  }
  function shuffle(){
    const indices=[...visibleOrder];
    for(let i=indices.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[indices[i],indices[j]]=[indices[j],indices[i]];}
    setOrder(indices);sounds.unlock();
  }
  function ask(kind){setConfirm(kind);}
  const status=!connected?'Reconnexion à OasisGame…':game.paused?'Partie en pause · reconnexion d’un joueur (2 minutes maximum)':
    game.phase==='lobby'?'Installez-vous autour du plateau':game.phase==='finished'?'La partie est terminée':
    playable?'À toi de jouer !':me?.retired?'Tu as quitté cette manche · spectateur':`Au tour de ${active?.name||'…'}`;

  return <main className="sg-page">
    <header className="sg-header"><span className="og-brand">✦ OasisGame</span><div>
      <button onClick={sounds.toggle} aria-label={sounds.enabled?'Couper les sons':'Activer les sons'}>{sounds.enabled?<Volume2 size={17}/>:<VolumeX size={17}/>}</button>
      <button onClick={()=>setRules(true)}><BookOpen size={16}/> Règles</button>
      {canControl&&<button onClick={()=>playing?ask('menu'):send({type:'choose_game',game:'menu'})}><ArrowLeft size={16}/> Tous les jeux</button>}
    </div></header>
    <div className="sg-title"><div><small>LE SALON DE JEUX DE L’OASIS</small><h1>Scrabble<span>À chaque lettre, une nouvelle idée.</span></h1></div><span className="sg-session"><Users size={16}/> {game.seats.length}/4 joueurs · Français</span></div>
    {error&&<p className="og-error" role="alert">{error}</p>}
    <div className={'sg-status'+(playable?' sg-your-turn':'')} role="status"><span className="sg-dot"/>{status}
      {playing&&remaining!==null&&<strong><Timer size={16}/>{Math.floor(remaining/60)}:{String(remaining%60).padStart(2,'0')}</strong>}
    </div>
    <div className="sg-layout"><section className="sg-stage" aria-label="Plateau et chevalet">
      <div className="sg-board-wrap"><div className="sg-columns" aria-hidden="true">{'ABCDEFGHIJKLMNO'.split('').map(c=><span key={c}>{c}</span>)}</div>
        <div className="sg-board" role="group" aria-label="Plateau de Scrabble, 15 lignes et 15 colonnes" onKeyDown={navigate}>
          {game.board.flatMap((line,row)=>line.map((tile,column)=>{
            const pending=draft.find(p=>p.row===row&&p.column===column);
            const bonus=game.premiums[row][column];
            const latest=history.at(-1)?.positions?.some(([r,c])=>r===row&&c===column);
            const letter=tile?.letter||(pending&&(rack[pending.index]==='?'?pending.letter:rack[pending.index]));
            return <button type="button" key={row*15+column} data-cell={row*15+column}
              tabIndex={focusedCell===row*15+column?0:-1} onFocus={()=>setFocusedCell(row*15+column)}
              className={`sg-cell sg-${bonus||'normal'}${pending?' sg-pending':''}${latest?' sg-latest':''}`}
              aria-label={`${String.fromCharCode(65+column)}${row+1}, ${letter||BONUS[bonus]||'case vide'}${pending?', lettre en préparation':''}`}
              aria-disabled={!playable||Boolean(tile)||exchange}
              onClick={()=>place(row,column)}
              onDragOver={e=>{if(playable&&!tile&&!exchange)e.preventDefault();}}
              onDrop={e=>{e.preventDefault();const raw=e.dataTransfer.getData('application/oasis-tile');if(raw!=='')place(row,column,Number(raw));}}>
              {letter?<Tile letter={letter} blank={tile?.blank||(pending&&rack[pending.index]==='?')}/>:
                row===7&&column===7?<span className="sg-star" aria-hidden="true">✦</span>:<span className="sg-bonus" aria-hidden="true">{BONUS[bonus]}</span>}
              {column===0&&<span className="sg-row-number" aria-hidden="true">{row+1}</span>}
            </button>;
          }))}
        </div>
      </div>
      {game.phase==='lobby'?<div className="sg-panel sg-lobby"><h2>Une partie entre amis</h2><p>De 2 à 4 joueurs. Les autres membres peuvent suivre la partie en spectateurs.</p>
        {!seat?<button className="sg-primary" disabled={!connected||game.seats.length>=4} onClick={()=>action('join')}>Prendre une place</button>:
          <button disabled={!connected} onClick={()=>action('leave')}>Libérer ma place</button>}
        {onInvite&&<button onClick={onInvite}><Users size={16}/> Inviter des amis</button>}
        {canControl&&<><label>Temps par tour<select disabled={!connected} value={game.settings.seconds} onChange={e=>action('settings',{field:'seconds',value:Number(e.target.value)})}>{[[0,'Sans limite'],[60,'1 minute'],[120,'2 minutes'],[180,'3 minutes'],[300,'5 minutes']].map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
          <button className="sg-primary" disabled={!connected||game.seats.length<2} onClick={()=>action('start')}>Lancer la partie <Check size={17}/></button></>}
      </div>:game.phase==='finished'?<div className="sg-panel sg-result" role="status"><small>PARTIE TERMINÉE</small>
        <h2>{game.result?.winners?.length>1?'Égalité !':game.result?.winners?.length?`${game.seats[game.result.winners[0]-1]?.name} remporte la partie !`:'Partie terminée'}</h2>
        <p>{REASONS[game.result?.reason]}</p><p>Les lettres restantes ont été déduites des scores.</p>
        {seat>0&&<button className="sg-primary" disabled={!connected||game.ready.includes(userId)||game.seats.some(s=>!s.connected)} onClick={()=>action('rematch')}><RotateCcw size={16}/>{game.ready.includes(userId)?'En attente des autres joueurs…':'Rejouer ensemble'}</button>}
        {canControl&&<button onClick={()=>action('reset')} disabled={!connected}>Nouvelle table</button>}
      </div>:<div className="sg-panel sg-rack-panel"><div className="sg-rack-heading"><strong>{seat?'Ton chevalet':'Mode spectateur'}</strong><span>{seat?'Tes lettres restent privées.':'Les chevalets des joueurs sont masqués.'}</span></div>
        {seat>0&&!me?.retired&&<><div className="sg-rack" role="group" aria-label="Ton chevalet">
          {visibleOrder.map(index=><button key={index} type="button" draggable={playable&&!exchange&&!draft.some(p=>p.index===index)}
            onDragStart={e=>{e.dataTransfer.setData('application/oasis-tile',String(index));setSelected(index);sounds.unlock();}}
            aria-label={`Lettre ${rack[index]==='?'?'joker':rack[index]}, ${VALUES[rack[index]]} point${VALUES[rack[index]]>1?'s':''}`}
            aria-pressed={selected===index||swaps.includes(index)} disabled={!playable}
            className={`${selected===index||swaps.includes(index)?'sg-selected ':''}${draft.some(p=>p.index===index)?'sg-used':''}`} onClick={()=>choose(index)}><Tile letter={rack[index]}/></button>)}
        </div><p className="sg-hint">{exchange?'Sélectionne les lettres à échanger. Cela termine ton tour.':'Choisis une lettre puis une case, ou glisse-la sur le plateau. Clique une lettre posée pour la reprendre.'}</p>
        <div className="sg-draft-feedback" aria-live="polite">{draft.length>0&&(validPreview?preview.valid?<><strong>+ {preview.score} points</strong><span>{preview.words.map(w=>w.word).join(' · ')}{preview.bingo?' · Bonus 7 lettres +50':''}</span></>:<span>{preview.detail}</span>:<span>Vérification du mot…</span>)}</div>
        <div className="sg-actions"><button disabled={!playable} onClick={shuffle}><Shuffle size={16}/> Mélanger</button>
          <button disabled={!playable||game.bag_count<7} onClick={()=>{setDraft([]);setSelected(null);setExchange(!exchange);setSwaps([]);}}>{exchange?'Annuler l’échange':'Échanger'}</button>
          {draft.length>0&&<button disabled={!playable} onClick={()=>{setDraft([]);setSelected(null);}}>Reprendre les lettres</button>}
          <button disabled={!playable} onClick={()=>ask('pass')}>Passer</button>
          <button className="sg-primary" disabled={!playable||(exchange?!swaps.length:!validPreview||!preview.valid)}
            onClick={()=>exchange?action('exchange',{indices:swaps}):action('play',{placements:draft})}><Check size={16}/>{exchange?'Échanger les lettres':'Valider le mot'}</button>
        </div></>}
      </div>}
    </section><aside className="sg-side">
      <section className="sg-panel"><h2><Users size={18}/> La partie</h2><p className="sg-muted">{game.spectators} spectateur{game.spectators>1?'s':''} · Manche {game.round||1}</p>
        <ol className="sg-players">{game.seats.map((s,i)=><li key={s.id} className={(playing&&game.turn===i+1?'sg-active ':'')+(s.retired?'sg-retired':'')}>
          <span className={'sg-avatar sg-avatar-'+i} aria-hidden="true">{s.name.slice(0,1).toUpperCase()}</span>
          <div><strong>{s.name}{s.id===userId?' (toi)':''}</strong><small>{s.retired?'Abandon':!s.connected?'Déconnecté':playing&&game.turn===i+1?'À toi de jouer':playing?`${s.tiles} lettres`:'À table'}</small></div><b>{game.score[i]||0}</b>
        </li>)}</ol>{game.seats.length===0&&<p className="sg-muted">La table attend ses joueurs.</p>}
      </section>
      <section className="sg-panel sg-bag"><span aria-hidden="true">◇</span><div><h2>Sac de lettres</h2><p>{game.bag_count} lettres restantes</p></div></section>
      <section className="sg-panel"><h2>Derniers coups</h2><ol className="sg-history">{[...history].reverse().slice(0,8).map((h,i)=><li key={game.ply-i}><span>{game.seats[h.player-1]?.name}<small>{h.kind==='play'?h.words.map(w=>w.word).join(' · '):({pass:'Passe son tour',exchange:`Échange ${h.count} lettre(s)`,resign:'Abandon',disconnect:'Déconnexion',timeout:'Temps écoulé'}[h.kind])}</small></span><b>{h.score?`+ ${h.score}`:'—'}</b></li>)}</ol>{!history.length&&<p className="sg-muted">Le premier mot reste à écrire.</p>}</section>
      <section className="sg-panel sg-chat"><h2><MessageCircle size={18}/> Discussion</h2><div ref={chatBox} className="sg-chat-messages" role="log" aria-label="Messages de la partie">{game.chat.map(m=><p key={m.id}><strong>{m.name}</strong><span>{m.text}</span></p>)}</div>
        <form onSubmit={e=>{e.preventDefault();if(chat.trim()&&connected){action('chat',{text:chat.trim()});setChat('');}}}><input aria-label="Message à la table" placeholder="Un mot à la table…" value={chat} maxLength={300} onChange={e=>setChat(e.target.value)}/><button disabled={!connected||!chat.trim()} aria-label="Envoyer le message">↗</button></form>
      </section><div className="sg-footer"><span>✓ Lexique français</span><button onClick={()=>setRules(true)}>Règles</button>{playing&&seat>0&&!me?.retired&&<button disabled={!connected} onClick={()=>ask('resign')}><Flag size={13}/> Abandonner</button>}</div>
    </aside></div>
    {(joker||confirm||rules)&&<div className="sg-overlay"><section ref={dialog} className="sg-dialog" role="dialog" aria-modal="true" aria-label={joker?'Choisir la lettre du joker':rules?'Règles du Scrabble':'Confirmer l’action'}>
      {joker?<><h2>Quelle lettre pour ton joker ?</h2><p>Un joker vaut zéro point, quelle que soit la lettre choisie.</p><div className="sg-alphabet">{ALPHABET.split('').map(letter=><button key={letter} onClick={()=>{setDraft(d=>[...d,{...joker,letter}]);setJoker(null);setSelected(null);}}>{letter}</button>)}</div><button onClick={()=>setJoker(null)}>Annuler</button></>:
        rules?<><small>LES RÈGLES DE LA TABLE</small><h2>Des lettres, des liens, des points.</h2><p>Le premier mot passe par l’étoile centrale. Ensuite, chaque mot doit se relier au plateau. Pose tes lettres sur une même ligne ou colonne, sans vide entre elles. Chaque mot formé, y compris les croisements, doit être valide.</p>
          <div className="sg-legend">{Object.entries(BONUS).map(([key,label])=><span className={'sg-'+key} key={key}>{label}</span>)}</div><p>Les bonus s’appliquent uniquement aux lettres nouvellement posées. Un joker vaut 0 point. Poser les 7 lettres rapporte 50 points supplémentaires.</p>
          <p>Tu peux échanger des lettres si le sac en contient au moins 7. Passer, échanger ou dépasser le temps termine ton tour. Après 6 tours consécutifs sans points, la partie s’arrête. Elle s’arrête aussi lorsqu’un joueur vide son chevalet et que le sac est vide.</p>
          <p>À la fin, les lettres restantes sont déduites des scores. Le joueur qui termine son chevalet reçoit les points des lettres des autres. Une déconnexion met la partie en pause pendant 2 minutes ; au-delà, le joueur est considéré comme ayant abandonné.</p>
          <p className="sg-muted">Validation locale : Lexique 3.83, Boris New, Christophe Pallier et contributeurs · CC BY-SA 4.0. Accents neutralisés, Œ → OE. Ce lexique peut différer du dictionnaire officiel de compétition.</p>
          <button className="sg-primary" autoFocus onClick={()=>setRules(false)}>C’est parti !</button></>:
          <><h2>{confirm==='pass'?'Passer ton tour ?':confirm==='menu'?'Fermer cette partie pour tout le monde ?':'Abandonner cette manche ?'}</h2><p>{confirm==='menu'?'Les scores et le plateau de cette partie seront perdus.':confirm==='resign'?'Les autres joueurs pourront continuer. Tu pourras suivre la suite en spectateur.':'Tes lettres restent sur ton chevalet. Tu pourras jouer à ton prochain tour.'}</p><div className="sg-actions"><button autoFocus onClick={()=>setConfirm(null)}>Annuler</button><button className="sg-primary" onClick={()=>{if(confirm==='menu')send({type:'choose_game',game:'menu'});else action(confirm);setConfirm(null);}}>Confirmer</button></div></>}
    </section></div>}
  </main>;
}
