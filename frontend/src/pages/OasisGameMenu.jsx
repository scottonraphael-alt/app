export default function OasisGameMenu({session,state,canControl,send,notice}){
 const allowed=String(session.channelId)===String(session.karaokeChannelId);
 const setup=state.mode==='blindtest_setup';
 return <main className="og-menu">
  <header><span className="og-brand">✦ OasisGame</span>{setup&&canControl&&<button onClick={()=>send({type:'choose_game',game:'menu'})}>← Tous les jeux</button>}</header>
  <div className="og-intro"><small>LE SALON DE JEUX DE L’OASIS</small><h1>{setup?'Prépare ton blind test':'À quoi joue-t-on ?'}</h1><p>{setup?'Choisis ton ambiance musicale, invite les autres et lance la partie.':'De la musique, des amis, et une nouvelle partie à partager.'}</p></div>
  {notice&&<p className="og-error" role="alert">{notice}</p>}
  {!canControl&&<p className="og-wait" role="status">L’hôte prépare la partie. Tu rejoindras le jeu avec les autres participants.</p>}
  {!setup&&<div className="og-games">
   <article className="og-game og-karaoke"><span aria-hidden="true">♫</span><small>À VOUS DE CHANTER</small><h2>Karaoké</h2><p>Paroles synchronisées, guide mélodique et défis vocaux.</p><button disabled={!canControl||!allowed} onClick={()=>send({type:'choose_game',game:'karaoke'})}>Entrer sur scène →</button>{!allowed&&<a href={'https://discord.com/channels/'+session.guildId+'/'+session.karaokeChannelId} target="_blank" rel="noreferrer">Rejoins le salon du karaoké et ouvre OasisGame depuis celui-ci.</a>}</article>
   <article className="og-game og-blindtest"><span aria-hidden="true">◎</span><small>À VOUS DE DEVINER</small><h2>Blind test</h2><p>Des extraits, tous les styles et une course aux bonnes réponses.</p><button disabled={!canControl} onClick={()=>send({type:'choose_game',game:'blindtest_setup'})}>Préparer une partie →</button></article>
  </div>}
 </main>;
}
