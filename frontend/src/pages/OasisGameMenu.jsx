export default function OasisGameMenu({session,state,canControl,send,notice,onInvite}){
 const allowed=String(session.channelId)===String(session.karaokeChannelId);
 const setup=state.mode==='blindtest_setup';
 return <main className="og-menu">
  <header><span className="og-brand">✦ OasisGame</span>{setup&&onInvite&&<button onClick={onInvite}>Inviter</button>}{setup&&canControl&&<button onClick={()=>send({type:'choose_game',game:'menu'})}>← Tous les jeux</button>}</header>
  <div className="og-intro"><small>LE SALON DE JEUX DE L’OASIS</small><h1>{setup?'Prépare ton blind test':'À quoi joue-t-on ?'}</h1><p>{setup?'Choisis ton ambiance musicale, invite les autres et lance la partie.':'Chante, devine les morceaux ou défie un ami.'}</p></div>
  {notice&&<p className="og-error" role="alert">{notice}</p>}
  {!canControl&&<p className="og-wait" role="status">L’hôte prépare la partie. Tu rejoindras le jeu avec les autres participants.</p>}
  {!setup&&<div className="og-games">
   <article className="og-game og-karaoke"><span aria-hidden="true">♫</span><small>À VOUS DE CHANTER</small><h2>Karaoké</h2><p>Paroles synchronisées, guide mélodique et défis vocaux.</p><button disabled={!canControl||!allowed} onClick={()=>send({type:'choose_game',game:'karaoke'})}>Entrer sur scène →</button>{!allowed&&<a href={'https://discord.com/channels/'+session.guildId+'/'+session.karaokeChannelId} target="_blank" rel="noreferrer">Rejoins le salon du karaoké et ouvre OasisGame depuis celui-ci.</a>}</article>
   <article className="og-game og-blindtest"><span aria-hidden="true">◎</span><small>À VOUS DE DEVINER</small><h2>Blind test</h2><p>Des extraits, tous les styles et une course aux bonnes réponses.</p><button disabled={!canControl} onClick={()=>send({type:'choose_game',game:'blindtest_setup'})}>Préparer une partie →</button></article>
   <article className="og-game og-connect-four"><span aria-hidden="true">⠿</span><small>À VOUS DE JOUER</small><h2>Puissance 4</h2><p>Aligne quatre jetons avant ton adversaire. Défie un ami ou joue contre l’ordinateur.</p><button disabled={!canControl} onClick={()=>send({type:'choose_game',game:'connect_four'})}>Ouvrir le plateau →</button></article>
   <article className="og-game og-morpion">
    <span aria-hidden="true">×○</span>
    <small>À VOUS DE JOUER</small>
    <h2>Morpion</h2>
    <p>Aligne trois croix ou trois ronds sur une grille de 3 × 3. Joue à deux ou contre l’ordinateur.</p>
    <button disabled={!canControl} onClick={() => send({ type: 'choose_game', game: 'tic_tac_toe' })}>Jouer au morpion →</button>
   </article>
   <article className="og-game og-scrabble"><span aria-hidden="true">A₁</span><small>À VOUS DE TROUVER LES MOTS</small><h2>Scrabble</h2><p>Une table, sept lettres et toutes vos idées. Composez vos mots et défiez vos amis à 2, 3 ou 4 joueurs.</p><button disabled={!canControl} onClick={()=>send({type:'choose_game',game:'scrabble'})}>Jouer avec les mots →</button></article>
   <article className="og-game og-minesweeper"><span aria-hidden="true">◇</span><small>À VOUS D’EXPLORER</small><h2>Démineur</h2><p>Un peu de logique, quelques drapeaux et une grille à apprivoiser. Joue en solo ou explore avec tes amis.</p><button disabled={!canControl} onClick={()=>send({type:'choose_game',game:'minesweeper'})}>Explorer la grille →</button></article>
  </div>}
 </main>;
}
