import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Bot, CircleHelp, Eye, Flag, RotateCcw, Timer, Users, X, Circle, Volume2, VolumeX } from "lucide-react";
import { useBoardSounds } from "./useBoardSounds";
import "./BoardGame.css";

const COLORS = ["", "Corail", "Menthe"];
const MARKS = ["", "Croix", "Rond"];
const GAMES = {
  connect_four: {
    name: "Puissance 4", prefix: "c4_", win: "Quatre jetons alignés",
    rules: "Choisis une colonne pour y faire tomber un jeton. Le premier qui en aligne quatre à l’horizontale, à la verticale ou en diagonale gagne.",
    keyboard: "Au clavier, utilise Tab pour rejoindre le plateau, les flèches pour changer de colonne et Entrée pour jouer.",
  },
  tic_tac_toe: {
    name: "Morpion", prefix: "ttt_", win: "Trois symboles alignés",
    rules: "Choisis une case libre pour placer ton symbole. Le premier qui aligne trois croix ou trois ronds à l’horizontale, à la verticale ou en diagonale gagne.",
    keyboard: "Au clavier, utilise Tab pour rejoindre le plateau, les flèches pour changer de case et Entrée pour jouer.",
  },
};
const SIZES = { compact: "Compact · 6 × 5", classic: "Classique · 7 × 6", large: "Grand · 8 × 7" };
const DIFFICULTIES = { easy: "Facile", medium: "Normal", hard: "Difficile" };
const RESULTS = {
  draw: "La grille est pleine",
  timeout: "Temps écoulé",
  resign: "Abandon",
  disconnect: "Délai de reconnexion dépassé",
  cancelled: "Les deux joueurs ont quitté la salle",
};

function ConnectFourBoard({ board, playable, last, winning, play }) {
  const columns = board[0].length;
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
    <div className="bg-board" role="group" aria-label="Plateau du Puissance 4" style={{ "--columns": columns }} onKeyDown={navigate}>
      {board[0].map((_, column) => {
        const available = playable && !board[0][column];
        const tokens = board.map(row => COLORS[row[column]] || "vide").reverse().join(", ");
        return (
          <button key={column} className="bg-column" type="button" tabIndex={playable ? 0 : -1}
            aria-label={`Colonne ${column + 1}, de bas en haut : ${tokens}`} aria-disabled={!available}
            onClick={() => available && play(column)}>
            <span className="bg-column-number" aria-hidden="true">{column + 1}</span>
            {board.map((row, index) => {
              const value = row[column];
              const latest = last?.row === index && last.column === column;
              const won = winning.some(([r, c]) => r === index && c === column);
              return (
                <span key={index} className="bg-hole" aria-hidden="true">
                  {value > 0 && <span className={`bg-token bg-token-${value}${latest ? " bg-last" : ""}${won ? " bg-win" : ""}`}
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

function Symbol({ player, className = "" }) {
  const Icon = player === 1 ? X : Circle;
  return <Icon className={`bg-symbol bg-symbol-${player} ${className}`} aria-hidden="true" />;
}

function TicTacToeBoard({ board, playable, seat, last, winning, play }) {
  function navigate(event) {
    const step = { ArrowUp: -3, ArrowDown: 3, ArrowLeft: -1, ArrowRight: 1 }[event.key];
    if (!step || event.target.dataset.cell === undefined) return;
    event.preventDefault();
    const current = Number(event.target.dataset.cell);
    const next = Math.abs(step) === 1
      ? 3 * Math.floor(current / 3) + (current % 3 + step + 3) % 3
      : (current + step + 9) % 9;
    event.currentTarget.querySelector(`[data-cell="${next}"]`)?.focus();
  }

  return (
    <div className="bg-board bg-morpion" role="group" aria-label="Plateau du morpion" onKeyDown={navigate}>
      {board.flat().map((player, cell) => {
        const row = Math.floor(cell / 3);
        const column = cell % 3;
        const available = playable && !player;
        const latest = last?.row === row && last.column === column;
        const won = winning.some(([r, c]) => r === row && c === column);
        return (
          <button key={cell} type="button" className={`bg-cell${won ? " bg-cell-win" : ""}`}
            data-cell={cell} tabIndex={playable ? 0 : -1}
            aria-label={`Ligne ${row + 1}, colonne ${column + 1} : ${MARKS[player] || "case libre"}`}
            aria-disabled={!available} onClick={() => available && play(cell)}>
            {player ? <Symbol player={player} className={latest ? "bg-symbol-last" : ""} /> :
              available && <Symbol player={seat} className="bg-symbol-preview" />}
          </button>
        );
      })}
    </div>
  );
}

function Board({ game, playable, replay, play, seat, morpion }) {
  const showingHistory = replay < game.history.length;
  const board = showingHistory ? game.board.map(row => row.map(() => 0)) : game.board;
  if (showingHistory) {
    game.history.slice(0, replay).forEach(({ row, column, player }) => { board[row][column] = player; });
  }
  const last = game.history[replay - 1];
  const winning = showingHistory ? [] : game.result?.line || [];

  const Grid = morpion ? TicTacToeBoard : ConnectFourBoard;
  return <Grid {...{ board, playable, last, winning, play, seat }} />;
}

function Lobby({ game, canControl, seat, connected, send }) {
  const { settings, seats } = game;
  const againstBot = settings.opponent === "bot";
  const full = seats.length === (againstBot ? 1 : 2);
  const set = (field, value) => send("settings", { field, value });
  const disabled = !connected || !canControl;

  return (
    <div className="bg-panel">
      <h2>Préparer le duel</h2>
      <div className="bg-options">
        <label>Adversaire
          <select value={settings.opponent} disabled={disabled} onChange={e => set("opponent", e.target.value)}>
            <option value="duel">Un autre joueur</option>
            <option value="bot" disabled={seats.length > 1}>L’ordinateur</option>
          </select>
        </label>
        {settings.size && <label>Grille
          <select value={settings.size} disabled={disabled} onChange={e => set("size", e.target.value)}>
            {Object.entries(SIZES).map(([value, name]) => <option key={value} value={value}>{name}</option>)}
          </select>
        </label>}
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
      <div className="bg-actions">
        {seat ? (
          <button disabled={!connected} onClick={() => send("leave")}>Libérer ma place</button>
        ) : (
          <button className="bg-primary" disabled={!connected || full} onClick={() => send("join")}>
            <Users size={16} /> Rejoindre le duel
          </button>
        )}
        {canControl && <button className={seat ? "bg-primary" : ""} disabled={!connected || !full}
          onClick={() => send("start")}>Lancer la partie <ArrowRight size={16} /></button>}
      </div>
      <p className="bg-muted">{full ? "Les places sont prises. L’hôte peut lancer le duel." : "Prends une place pour jouer. Les autres peuvent regarder."}</p>
    </div>
  );
}

function Players({ game, userId, morpion }) {
  return (
    <div className="bg-players" aria-label="Joueurs et scores">
      {(morpion ? MARKS : COLORS).slice(1).map((color, index) => {
        const seat = game.seats[index];
        const bot = seat?.id === "computer" || (!seat && index === 1 && game.settings.opponent === "bot");
        const name = seat?.name || (bot ? "Ordinateur" : "Place libre");
        const active = game.phase === "playing" && game.turn === index + 1;
        return (
          <div key={color} className={`bg-player bg-player-${index + 1}${active ? " bg-current" : ""}`}>
            {morpion ? <Symbol player={index + 1} /> : <span className={`bg-token bg-token-${index + 1}`} aria-hidden="true" />}
            <div>
              <span className="bg-muted">{color}{active ? " · À jouer" : ""}</span>
              <strong>{bot && <Bot size={15} />}{name}{seat?.id === userId ? " (toi)" : ""}</strong>
              {seat && !seat.connected && <small>Déconnecté</small>}
            </div>
            <span className="bg-score" aria-label={`${game.score[index]} victoires`}>{game.score[index]}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function BoardGame({ state, userId, canControl, connected, send, error, onInvite }) {
  const mode = state.mode;
  const game = state[mode];
  const sounds = useBoardSounds(mode, game.round_id, game.history.length, connected);
  const variant = GAMES[mode];
  const morpion = mode === "tic_tac_toe";
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
  const sendAction = (action, fields) => send({ type: variant.prefix + action, ...fields });
  const roundAction = (action, fields) => sendAction(action, { round_id: game.round_id, ...fields });
  const play = position => roundAction(morpion ? "place" : "drop", {
    [morpion ? "cell" : "column"]: position,
    ply: game.history.length,
  });
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
    <main className="bg-page" onClickCapture={sounds.enabled ? sounds.unlock : undefined}
      onKeyDownCapture={sounds.enabled ? sounds.unlock : undefined}>
      <header className="bg-header">
        <span className="og-brand">✦ OasisGame</span>
        <div className="bg-header-actions">
          <button type="button" onClick={sounds.toggle} aria-pressed={sounds.enabled}>
            {sounds.enabled ? <Volume2 size={17} /> : <VolumeX size={17} />} Bruitages
          </button>
          {onInvite && <button type="button" onClick={onInvite}><Users size={16} /> Inviter</button>}
          {canControl && <button disabled={!connected} onClick={() => send({ type: "choose_game", game: "menu" })}><ArrowLeft size={16} /> Tous les jeux</button>}
        </div>
      </header>
      <div className="bg-title">
        <div><span>LES DUELS DE L’OASIS</span><h1>{variant.name}</h1></div>
        <div className="bg-spectators"><Eye size={17} /> {game.spectators} spectateur{game.spectators === 1 ? "" : "s"}</div>
      </div>
      <div className="bg-layout">
        <div className="bg-stage">
          <Players game={game} userId={userId} morpion={morpion} />
          <div className="bg-status">
            <strong role="status">{status}</strong>
            {remaining !== null && <span className="bg-clock"><Timer size={17} />{Math.ceil(remaining)} s</span>}
          </div>
          {hasClock && <progress aria-label="Temps restant" max={game.settings.seconds} value={remaining} />}
          <Board key={game.round_id || game.settings.size} game={game} replay={frame} playable={playable} play={play} seat={seat} morpion={morpion} />
          {finished && game.history.length > 0 && <div className="bg-replay">
            <button aria-label="Coup précédent" disabled={frame === 0} onClick={() => scrub(frame - 1)}><ArrowLeft size={17} /></button>
            <label>Rejouer les coups <input type="range" min="0" max={game.history.length} value={frame} onChange={e => scrub(Number(e.target.value))} /></label>
            <span>{frame}/{game.history.length}</span>
            <button aria-label="Coup suivant" disabled={frame === game.history.length} onClick={() => scrub(frame + 1)}><ArrowRight size={17} /></button>
          </div>}
        </div>
        <aside className="bg-side">
          {error && <p className="og-error" role="alert">{error}</p>}
          {game.phase === "lobby" && <Lobby {...{ game, canControl, seat, connected }} send={sendAction} />}
          {playing && <div className="bg-panel">
            <h2>Manche {game.round}</h2>
            <p className="bg-muted">{morpion ? "Grille 3 × 3" : SIZES[game.settings.size]} · {game.history.length} coup{game.history.length === 1 ? "" : "s"}</p>
            {paused && <p>La partie est en pause. Un joueur déconnecté a 30 secondes pour revenir.</p>}
            {!seat && <p>Tu regardes le duel en tant que spectateur.</p>}
            {seat > 0 && !paused && (
              confirmResign === game.round_id ? <div className="bg-actions">
                <button disabled={!connected} onClick={() => roundAction("resign")}>Confirmer l’abandon</button>
                <button onClick={() => setConfirmResign(null)}>Annuler</button>
              </div> : <button disabled={!connected} onClick={() => setConfirmResign(game.round_id)}><Flag size={15} /> Abandonner</button>
            )}
          </div>}
          {finished && <div className="bg-panel">
            <h2>Fin de la manche {game.round}</h2>
            <p>{game.result.reason === "win" ? variant.win : RESULTS[game.result.reason]}</p>
            <p className="bg-muted">{game.draws} match{game.draws === 1 ? "" : "s"} nul{game.draws === 1 ? "" : "s"} dans ce duel</p>
            <div className="bg-actions">
              {seat > 0 && game.result.reason !== "cancelled" && <button className="bg-primary"
                disabled={!connected || game.ready.includes(userId) || game.seats.some(player => !player.connected)}
                onClick={() => roundAction("rematch")}><RotateCcw size={16} /> {game.ready.includes(userId) ? "En attente de l’adversaire" : game.ready.length ? "Accepter la revanche" : "Revanche"}</button>}
              {canControl && <button disabled={!connected} onClick={() => sendAction("reset")}>Nouveau duel</button>}
            </div>
          </div>}
          <details className="bg-panel bg-rules">
            <summary><CircleHelp size={17} /> Règles du jeu</summary>
            <p>{variant.rules}</p>
            <p>Si la grille est pleine, c’est un match nul. Le premier joueur change à chaque revanche.</p>
            <p>{variant.keyboard}</p>
          </details>
        </aside>
      </div>
    </main>
  );
}
