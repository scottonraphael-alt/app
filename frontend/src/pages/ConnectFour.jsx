import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Bot, CircleHelp, Eye, Flag, RotateCcw, Timer, Users } from "lucide-react";
import "./ConnectFour.css";

const COLORS = ["", "Corail", "Menthe"];
const SIZES = { compact: "Compact · 6 × 5", classic: "Classique · 7 × 6", large: "Grand · 8 × 7" };
const DIFFICULTIES = { easy: "Facile", medium: "Normal", hard: "Difficile" };
const RESULTS = {
  win: "Quatre jetons alignés",
  draw: "La grille est pleine",
  timeout: "Temps écoulé",
  resign: "Abandon",
  disconnect: "Délai de reconnexion dépassé",
  cancelled: "Les deux joueurs ont quitté la salle",
};

function Board({ game, playable, replay, drop }) {
  const columns = game.board[0].length;
  const showingHistory = replay < game.history.length;
  const board = showingHistory ? game.board.map(row => row.map(() => 0)) : game.board;
  if (showingHistory) {
    game.history.slice(0, replay).forEach(({ row, column, player }) => { board[row][column] = player; });
  }
  const last = game.history[replay - 1];
  const winning = showingHistory ? [] : game.result?.line || [];

  function navigate(event) {
    const buttons = Array.from(event.currentTarget.querySelectorAll("button"));
    const index = buttons.indexOf(event.target);
    if (index < 0) return;
    const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    if (!step) return;
    event.preventDefault();
    buttons[(index + step + columns) % columns].focus();
  }

  return (
    <div className="c4-board" role="group" aria-label="Plateau du Puissance 4" style={{ "--columns": columns }} onKeyDown={navigate}>
      {board[0].map((_, column) => {
        const available = playable && !board[0][column];
        const tokens = board.map(row => COLORS[row[column]] || "vide").reverse().join(", ");
        return (
          <button key={column} className="c4-column" type="button" tabIndex={playable ? 0 : -1}
            aria-label={`Colonne ${column + 1}, de bas en haut : ${tokens}`} aria-disabled={!available}
            onClick={() => available && drop(column)}>
            <span className="c4-column-number" aria-hidden="true">{column + 1}</span>
            {board.map((row, index) => {
              const value = row[column];
              const latest = last?.row === index && last.column === column;
              const won = winning.some(([r, c]) => r === index && c === column);
              return (
                <span key={index} className="c4-hole" aria-hidden="true">
                  {value > 0 && <span className={`c4-token c4-token-${value}${latest ? " c4-last" : ""}${won ? " c4-win" : ""}`}
                    style={{ "--fall": index + 1 }} />}
                </span>
              );
            })}
          </button>
        );
      })}
    </div>
  );
}

function Lobby({ game, canControl, seat, connected, send }) {
  const { settings, seats } = game;
  const againstBot = settings.opponent === "bot";
  const full = seats.length === (againstBot ? 1 : 2);
  const set = (field, value) => send({ type: "c4_settings", field, value });
  const disabled = !connected || !canControl;

  return (
    <div className="c4-panel">
      <h2>Préparer le duel</h2>
      <div className="c4-options">
        <label>Adversaire
          <select value={settings.opponent} disabled={disabled} onChange={e => set("opponent", e.target.value)}>
            <option value="duel">Un autre joueur</option>
            <option value="bot" disabled={seats.length > 1}>L’ordinateur</option>
          </select>
        </label>
        <label>Grille
          <select value={settings.size} disabled={disabled} onChange={e => set("size", e.target.value)}>
            {Object.entries(SIZES).map(([value, name]) => <option key={value} value={value}>{name}</option>)}
          </select>
        </label>
        <label>Temps par tour
          <select value={settings.seconds} disabled={disabled} onChange={e => set("seconds", Number(e.target.value))}>
            {[0, 15, 30, 60].map(seconds => <option key={seconds} value={seconds}>{seconds ? `${seconds} secondes` : "Sans chrono"}</option>)}
          </select>
        </label>
        {againstBot && <label>Difficulté
          <select value={settings.difficulty} disabled={disabled} onChange={e => set("difficulty", e.target.value)}>
            {Object.entries(DIFFICULTIES).map(([value, name]) => <option key={value} value={value}>{name}</option>)}
          </select>
        </label>}
      </div>
      <div className="c4-actions">
        {seat ? (
          <button disabled={!connected} onClick={() => send({ type: "c4_leave" })}>Libérer ma place</button>
        ) : (
          <button className="c4-primary" disabled={!connected || full} onClick={() => send({ type: "c4_join" })}>
            <Users size={16} /> Rejoindre le duel
          </button>
        )}
        {canControl && <button className={seat ? "c4-primary" : ""} disabled={!connected || !full}
          onClick={() => send({ type: "c4_start" })}>Lancer la partie <ArrowRight size={16} /></button>}
      </div>
      <p className="c4-muted">{full ? "Les places sont prises. L’hôte peut lancer le duel." : "Prends une place pour jouer. Les autres peuvent regarder."}</p>
    </div>
  );
}

function Players({ game, userId }) {
  return (
    <div className="c4-players" aria-label="Joueurs et scores">
      {COLORS.slice(1).map((color, index) => {
        const seat = game.seats[index];
        const bot = seat?.id === "computer" || (!seat && index === 1 && game.settings.opponent === "bot");
        const name = seat?.name || (bot ? "Ordinateur" : "Place libre");
        const active = game.phase === "playing" && game.turn === index + 1;
        return (
          <div key={color} className={`c4-player c4-player-${index + 1}${active ? " c4-current" : ""}`}>
            <span className={`c4-token c4-token-${index + 1}`} aria-hidden="true" />
            <div>
              <span className="c4-muted">{color}{active ? " · À jouer" : ""}</span>
              <strong>{bot && <Bot size={15} />}{name}{seat?.id === userId ? " (toi)" : ""}</strong>
              {seat && !seat.connected && <small>Déconnecté</small>}
            </div>
            <span className="c4-score" aria-label={`${game.score[index]} victoires`}>{game.score[index]}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function ConnectFour({ state, userId, canControl, connected, send, error }) {
  const game = state.connect_four;
  const seat = game.seats.findIndex(player => player.id === userId) + 1;
  const playing = game.phase === "playing";
  const paused = playing && game.seats.some(player => !player.connected);
  const playable = connected && playing && !paused && seat === game.turn;
  const finished = game.phase === "finished";
  const [now, setNow] = useState(() => performance.now());
  const [replay, setReplay] = useState(null);
  const [confirmResign, setConfirmResign] = useState(null);
  const hasClock = playing && !paused && game.remaining !== null;
  useEffect(() => {
    if (!hasClock) return undefined;
    const id = window.setInterval(() => setNow(performance.now()), 150);
    return () => window.clearInterval(id);
  }, [hasClock]);
  const move = (type, fields) => send({ type, round_id: game.round_id, ...fields });
  const drop = column => move("c4_drop", { column, ply: game.history.length });
  const activeName = game.seats[game.turn - 1]?.name;
  const winner = game.seats[(game.result?.winner || 0) - 1];
  const frame = replay?.id === game.round_id && finished ? replay.index : game.history.length;
  const scrub = index => setReplay({ id: game.round_id, index });
  const status = !connected ? "Reconnexion à OasisGame…" : paused ? "En attente de la reconnexion d’un joueur…" :
    playable ? "À toi de jouer" : playing ? `Au tour de ${activeName}` :
    finished ? winner ? `${winner.name} remporte la manche` :
      game.result.reason === "draw" ? "Match nul" : "Manche annulée" : "En attente des joueurs";
  const remaining = hasClock ? Math.max(0, game.remaining - Math.max(0, now - state.at) / 1000) : game.remaining;

  return (
    <main className="c4-page">
      <header className="c4-header">
        <span className="og-brand">✦ OasisGame</span>
        {canControl && <button disabled={!connected} onClick={() => send({ type: "choose_game", game: "menu" })}><ArrowLeft size={16} /> Tous les jeux</button>}
      </header>
      <div className="c4-title">
        <div><span>LES DUELS DE L’OASIS</span><h1>Puissance 4</h1></div>
        <div className="c4-spectators"><Eye size={17} /> {game.spectators} spectateur{game.spectators === 1 ? "" : "s"}</div>
      </div>
      <div className="c4-layout">
        <div className="c4-stage">
          <Players game={game} userId={userId} />
          <div className="c4-status">
            <strong role="status">{status}</strong>
            {remaining !== null && <span className="c4-clock"><Timer size={17} />{Math.ceil(remaining)} s</span>}
          </div>
          {hasClock && <progress aria-label="Temps restant" max={game.settings.seconds} value={remaining} />}
          <Board key={game.round_id || game.settings.size} game={game} replay={frame} playable={playable} drop={drop} />
          {finished && game.history.length > 0 && <div className="c4-replay">
            <button aria-label="Coup précédent" disabled={frame === 0} onClick={() => scrub(frame - 1)}><ArrowLeft size={17} /></button>
            <label>Rejouer les coups <input type="range" min="0" max={game.history.length} value={frame} onChange={e => scrub(Number(e.target.value))} /></label>
            <span>{frame}/{game.history.length}</span>
            <button aria-label="Coup suivant" disabled={frame === game.history.length} onClick={() => scrub(frame + 1)}><ArrowRight size={17} /></button>
          </div>}
        </div>
        <aside className="c4-side">
          {error && <p className="og-error" role="alert">{error}</p>}
          {game.phase === "lobby" && <Lobby {...{ game, canControl, seat, connected, send }} />}
          {playing && <div className="c4-panel">
            <h2>Manche {game.round}</h2>
            <p className="c4-muted">{SIZES[game.settings.size]} · {game.history.length} coup{game.history.length === 1 ? "" : "s"}</p>
            {paused && <p>La partie est en pause. Un joueur déconnecté a 30 secondes pour revenir.</p>}
            {!seat && <p>Tu regardes le duel en tant que spectateur.</p>}
            {seat > 0 && !paused && (
              confirmResign === game.round_id ? <div className="c4-actions">
                <button disabled={!connected} onClick={() => move("c4_resign")}>Confirmer l’abandon</button>
                <button onClick={() => setConfirmResign(null)}>Annuler</button>
              </div> : <button disabled={!connected} onClick={() => setConfirmResign(game.round_id)}><Flag size={15} /> Abandonner</button>
            )}
          </div>}
          {finished && <div className="c4-panel">
            <h2>Fin de la manche {game.round}</h2>
            <p>{RESULTS[game.result.reason]}</p>
            <p className="c4-muted">{game.draws} match{game.draws === 1 ? "" : "s"} nul{game.draws === 1 ? "" : "s"} dans ce duel</p>
            <div className="c4-actions">
              {seat > 0 && game.result.reason !== "cancelled" && <button className="c4-primary"
                disabled={!connected || game.ready.includes(userId) || game.seats.some(player => !player.connected)}
                onClick={() => move("c4_rematch")}><RotateCcw size={16} /> {game.ready.includes(userId) ? "En attente de l’adversaire" : game.ready.length ? "Accepter la revanche" : "Revanche"}</button>}
              {canControl && <button disabled={!connected} onClick={() => send({ type: "c4_reset" })}>Nouveau duel</button>}
            </div>
          </div>}
          <details className="c4-panel c4-rules">
            <summary><CircleHelp size={17} /> Règles du jeu</summary>
            <p>Choisis une colonne pour y faire tomber un jeton. Le premier qui en aligne quatre à l’horizontale, à la verticale ou en diagonale gagne.</p>
            <p>Si la grille est pleine, c’est un match nul. Le premier joueur change à chaque revanche.</p>
            <p>Au clavier, utilise Tab pour rejoindre le plateau, les flèches pour changer de colonne et Entrée pour jouer.</p>
          </details>
        </aside>
      </div>
    </main>
  );
}
