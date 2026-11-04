import { useCallback, useEffect, useRef, useState } from "react";
import KaraokeLyrics, { LYRICS_FONT } from "./KaraokeLyrics";
import KaraokeTools from "./KaraokeTools";
import KaraokeBackdrop from "./KaraokeBackdrop";

// Même principe que CinéStream : tout passe par /.proxy (URL Mappings du portail Discord).
const DEFAULT_PROXY = "/.proxy/backend/api";
const SYNC_INTERVAL_MS = 5000;
const DRIFT_SECONDS = 1.2;

const CATEGORY_LABELS = { title: "Titre", artist: "Artiste", source: "Source" };
const NOTICES = {
  game_running: "Une partie est en cours : arrête-la avant de changer de morceau.",
  empty_library: "Aucun morceau disponible : dossier vide et catalogue Deezer pas encore chargé (réessaie dans un instant).",
};

const KEYFRAMES = `
@keyframes kEq { 0%,100% { transform: scaleY(0.25); } 50% { transform: scaleY(1); } }
@keyframes kPop { 0% { transform: scale(0.9); opacity: 0; } 100% { transform: scale(1); opacity: 1; } }
`;

const S = {
  page: {
    position: "relative",
    width: "100vw",
    height: "100vh",
    display: "flex",
    flexDirection: "column",
    color: "#fff",
    fontFamily: LYRICS_FONT,
    overflow: "hidden",
    background: "radial-gradient(1200px 700px at 50% -10%, #3a1b5e 0%, #14101f 55%, #08070d 100%)",
  },
  top: { display: "flex", alignItems: "center", gap: 10, padding: "12px 16px", flexWrap: "wrap" },
  badge: { padding: "6px 12px", borderRadius: 999, background: "rgba(0,0,0,0.45)", fontSize: 14, fontWeight: 600 },
  main: { flex: 1, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: "0 8px" },
  bar: {
    margin: "0 auto 16px",
    width: "min(820px, calc(100vw - 24px))",
    display: "flex",
    flexDirection: "column",
    gap: 10,
    padding: 12,
    borderRadius: 14,
    background: "rgba(0,0,0,0.55)",
  },
  row: { display: "flex", justifyContent: "center", alignItems: "center", gap: 10, flexWrap: "wrap" },
  button: {
    padding: "9px 18px",
    borderRadius: 999,
    border: "none",
    background: "rgba(255,255,255,0.92)",
    color: "#111",
    fontSize: 15,
    fontWeight: 700,
    cursor: "pointer",
  },
  ghost: {
    padding: "7px 12px",
    borderRadius: 999,
    border: "1px solid rgba(255,255,255,0.3)",
    background: "transparent",
    color: "#fff",
    fontSize: 14,
    cursor: "pointer",
  },
  panel: {
    margin: "0 auto 8px",
    width: "min(560px, calc(100vw - 24px))",
    maxHeight: "40vh",
    overflowY: "auto",
    padding: 8,
    borderRadius: 12,
    background: "rgba(20,20,26,0.97)",
    border: "1px solid rgba(255,255,255,0.15)",
  },
  item: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    width: "100%",
    padding: "9px 12px",
    border: "none",
    borderRadius: 8,
    background: "transparent",
    color: "#fff",
    fontSize: 15,
    textAlign: "left",
    cursor: "pointer",
  },
  card: { background: "rgba(0,0,0,0.5)", borderRadius: 16, padding: 18 },
  overlay: {
    position: "absolute",
    inset: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "rgba(0,0,0,0.65)",
    border: "none",
    color: "#fff",
    fontSize: 20,
    cursor: "pointer",
    zIndex: 5,
  },
};

function loadPref(key, fallback) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch (e) {
    return fallback; // stockage indisponible dans l'iframe : valeur par défaut
  }
}

function savePref(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch (e) {
    // sans conséquence : la préférence ne sera simplement pas mémorisée
  }
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function useNow(active) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => setNow(performance.now()), 200);
    return () => window.clearInterval(timer);
  }, [active]);
  return now;
}

function Equalizer({ running }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "center", gap: 5, height: 90 }}>
      {Array.from({ length: 24 }, (_, i) => (
        <div
          key={i}
          style={{
            width: 8,
            height: "100%",
            borderRadius: 4,
            background: "linear-gradient(180deg, #ff6ec4, #7c5cff)",
            transformOrigin: "bottom",
            transform: "scaleY(0.25)",
            animation: running ? `kEq ${0.7 + (i % 7) * 0.13}s ease-in-out ${(i % 5) * 0.09}s infinite` : "none",
          }}
        />
      ))}
    </div>
  );
}

function Scoreboard({ scores, userId, compact }) {
  const rows = scores.slice(0, compact ? 5 : 8);
  if (rows.length === 0) return null;
  return (
    <div style={{ ...S.card, minWidth: 220 }}>
      <div style={{ fontSize: 13, opacity: 0.7, marginBottom: 8 }}>Classement</div>
      {rows.map((row, i) => (
        <div
          key={row.id}
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 12,
            padding: "4px 0",
            fontWeight: row.id === userId ? 800 : 500,
            color: row.id === userId ? "#ff9bd6" : "#fff",
          }}
        >
          <span>{i + 1}. {row.name}</span>
          <span style={{ fontVariantNumeric: "tabular-nums" }}>
            {row.score}
            {row.delta > 0 && <span style={{ color: "#7dffb0", marginLeft: 6 }}>+{row.delta}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

function BlindTestView({ state, send, canControl, userId, feedback, plays, setPlays, inputRef }) {
  const bt = state.bt;
  const round = bt.round;
  const [guess, setGuess] = useState("");
  const active = bt.phase === "round" || bt.phase === "reveal";
  const now = useNow(active);
  const waited = (now - state.at) / 1000;

  useEffect(() => {
    setGuess("");
    if (bt.phase === "round" && inputRef.current) inputRef.current.focus();
  }, [bt.index, bt.phase, inputRef]);

  const submit = (event) => {
    event.preventDefault();
    const text = guess.trim();
    if (!text) return;
    send({ type: "guess", text });
    setGuess("");
  };

  const mine = round ? round.found.find((entry) => entry.id === userId) : null;
  const remaining = round && bt.phase === "round" ? Math.max(0, round.remaining - waited) : 0;
  const revealLeft = round && bt.phase === "reveal" ? Math.max(0, (round.reveal_remaining || 0) - waited) : 0;

  const controls = canControl && (
    <div style={S.row}>
      {bt.phase !== "final" && (
        <button type="button" style={S.ghost} onClick={() => send({ type: "bt_skip" })}>
          {bt.phase === "round" ? "⏭ Révéler" : "⏭ Suivant"}
        </button>
      )}
      {bt.phase === "final" && (
        <button type="button" style={S.button} onClick={() => send({ type: "bt_start", rounds: bt.total, seconds: bt.seconds })}>
          🔁 Rejouer
        </button>
      )}
      <button type="button" style={S.ghost} onClick={() => send({ type: "bt_stop" })}>
        {bt.phase === "final" ? "🎤 Retour au karaoké" : "⏹ Arrêter"}
      </button>
      <label style={{ fontSize: 14, display: "flex", gap: 6, alignItems: "center" }}>
        <input type="checkbox" checked={plays} onChange={(event) => setPlays(event.target.checked)} />
        Je participe
      </label>
    </div>
  );

  if (bt.phase === "final") {
    const podium = bt.scores.slice(0, 3);
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 18, alignItems: "center", padding: 16 }}>
        <div style={{ fontSize: "clamp(26px, 4vw, 44px)", fontWeight: 800 }}>🏆 Fin de la partie</div>
        <div style={{ display: "flex", gap: 14, alignItems: "flex-end", flexWrap: "wrap", justifyContent: "center" }}>
          {podium.map((row, i) => (
            <div key={row.id} style={{ ...S.card, textAlign: "center", minWidth: 130, paddingTop: 18 + i * 14 }}>
              <div style={{ fontSize: 34 }}>{["🥇", "🥈", "🥉"][i]}</div>
              <div style={{ fontWeight: 800 }}>{row.name}</div>
              <div style={{ opacity: 0.8 }}>{row.score} pts · {row.titles} titre{row.titles > 1 ? "s" : ""}</div>
            </div>
          ))}
        </div>
        <Scoreboard scores={bt.scores} userId={userId} />
        {controls}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: 20, alignItems: "flex-start", justifyContent: "center", flexWrap: "wrap", padding: 16, width: "100%" }}>
      <div style={{ flex: "1 1 420px", maxWidth: 640, display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ ...S.row, justifyContent: "space-between" }}>
          <div style={{ fontWeight: 800, fontSize: 18 }}>🎯 Manche {bt.index} / {bt.total}</div>
          <div style={{ fontVariantNumeric: "tabular-nums", fontWeight: 700 }}>
            {bt.phase === "round" ? `${Math.ceil(remaining)} s` : `Suite dans ${Math.ceil(revealLeft)} s`}
          </div>
        </div>
        {bt.phase === "round" && (
          <div style={{ height: 8, borderRadius: 4, background: "rgba(255,255,255,0.15)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${(remaining / bt.seconds) * 100}%`, background: "linear-gradient(90deg,#ff6ec4,#7c5cff)", transition: "width 200ms linear" }} />
          </div>
        )}

        {bt.phase === "round" ? (
          <>
            <Equalizer running />
            <div style={{ ...S.row, justifyContent: "center" }}>
              {round.asks.map((category) => {
                const found = mine && mine.categories.includes(category);
                return (
                  <span key={category} style={{ ...S.badge, background: found ? "rgba(80,220,140,0.3)" : "rgba(255,255,255,0.12)" }}>
                    {found ? "✓ " : "? "}{CATEGORY_LABELS[category]}
                  </span>
                );
              })}
            </div>
            <form onSubmit={submit} style={S.row}>
              <input
                ref={inputRef}
                value={guess}
                onChange={(event) => setGuess(event.target.value)}
                placeholder={plays ? "Titre, artiste ou source… (romaji accepté)" : "Tu es spectateur"}
                disabled={!plays}
                maxLength={120}
                autoComplete="off"
                style={{ flex: 1, minWidth: 220, padding: "12px 16px", borderRadius: 999, border: "1px solid rgba(255,255,255,0.3)", background: "rgba(0,0,0,0.5)", color: "#fff", fontSize: 17, fontFamily: LYRICS_FONT }}
              />
              <button type="submit" style={S.button} disabled={!plays}>Valider</button>
            </form>
            <div style={{ minHeight: 26, textAlign: "center", fontWeight: 700 }}>
              {feedback && feedback.status === "ok" && (
                <span key={feedback.key} style={{ color: "#7dffb0", animation: "kPop 200ms ease" }}>
                  ✓ {feedback.found.map((c) => CATEGORY_LABELS[c]).join(" + ")} trouvé ! +{feedback.points} pts
                </span>
              )}
              {feedback && feedback.status === "wrong" && (
                <span key={feedback.key} style={{ color: "#ff8a8a", animation: "kPop 200ms ease" }}>✗ Ce n'est pas ça…</span>
              )}
              {feedback && feedback.status === "throttled" && <span style={{ color: "#ffd27d" }}>Trop d'essais pour cette manche.</span>}
            </div>
          </>
        ) : (
          <div style={{ ...S.card, textAlign: "center", animation: "kPop 250ms ease" }}>
            <div style={{ fontSize: 14, opacity: 0.7 }}>C'était…</div>
            <div style={{ fontSize: "clamp(24px, 4vw, 40px)", fontWeight: 800, margin: "6px 0" }}>{round.answer.title}</div>
            {round.answer.artist && <div style={{ fontSize: 20 }}>{round.answer.artist}</div>}
            {round.answer.source && <div style={{ opacity: 0.8, marginTop: 4 }}>{round.answer.source}</div>}
            <div style={{ marginTop: 12, fontSize: 14, opacity: 0.85 }}>
              {round.found.length === 0
                ? "Personne n'a trouvé."
                : round.found.map((entry) => entry.name).join(", ") + " ont trouvé !"}
            </div>
          </div>
        )}
        {bt.phase === "round" && round.found.length > 0 && (
          <div style={{ fontSize: 14, opacity: 0.85, textAlign: "center" }}>
            {round.found.map((entry) => `✓ ${entry.name}`).join("  ")}
          </div>
        )}
        {controls}
      </div>
      <Scoreboard scores={bt.scores} userId={userId} />
    </div>
  );
}

export default function KaraokeStage({ session, onExit }) {
  const { videoToken, instanceId, canControl, userName, userId } = session;
  const PROXY = session.apiRoot || DEFAULT_PROXY;
  const [favorites, setFavorites] = useState([]);
  const [preparationRevision, setPreparationRevision] = useState(0);
  const onPrepared = useCallback(() => setPreparationRevision(v => v + 1), []);
  const [connected, setConnected] = useState(false);
  const [state, setState] = useState(null);
  const [library, setLibrary] = useState([]);
  const localTracks = library.filter((item) => !item.preview); // les extraits de 30 s ne servent qu'au blind test
  const [lyrics, setLyrics] = useState({ status: "idle", lines: [] });
  const [lyricsGate, setLyricsGate] = useState(null);
  const [needsClick, setNeedsClick] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [seekPreview, setSeekPreview] = useState(null);
  const [volume, setVolume] = useState(() => loadPref("karaoke.volume", 0.8));
  const [showRomaji, setShowRomaji] = useState(() => loadPref("karaoke.romaji", true));
  const [offset, setOffset] = useState(() => loadPref("karaoke.offset", 0));
  const [plays, setPlays] = useState(true);
  const [feedback, setFeedback] = useState(null);
  const [notice, setNotice] = useState("");
  const [panel, setPanel] = useState(null); // "tracks" | "blindtest" | null
  const [settings, setSettings] = useState({ rounds: 10, seconds: 20, pool: "all" });

  const audioRef = useRef(null);
  const socketRef = useRef(null);
  const stateRef = useRef(null);
  const inputRef = useRef(null);

  const mode = state ? state.mode : "karaoke";
  const track = state && state.karaoke ? state.karaoke.track : null;
  const playing = state && state.karaoke ? state.karaoke.playing : false;
  const trackId = mode === "karaoke" && track ? track.id : null;

  const send = useCallback((payload) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
  }, []);

  // --- Connexion WebSocket (reconnexion automatique, comme CinéStream) -----------------
  useEffect(() => {
    let closed = false;
    let retries = 0;
    let reconnectTimer;

    const connect = () => {
      const query = new URLSearchParams({ t: videoToken, instance_id: instanceId });
      const endpoint = new URL(`${PROXY}/activity/karaoke/ws`, window.location.href);
      endpoint.protocol = endpoint.protocol === "https:" ? "wss:" : "ws:";
      endpoint.search = query.toString();
      const socket = new WebSocket(endpoint.toString());
      socketRef.current = socket;
      socket.onopen = () => {
        retries = 0;
        setConnected(true);
      };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "kstate") {
          const stamped = { ...message, at: performance.now() };
          stateRef.current = stamped;
          setState(stamped);
        } else if (message.type === "favorites") {
          setFavorites(message.ids || []);
        } else if (message.type === "library") {
          setLibrary(message.tracks || []);
        } else if (message.type === "guess_result") {
          setFeedback({ ...message, key: Date.now() });
        } else if (message.type === "error") {
          setNotice(NOTICES[message.code] || "Action impossible.");
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (!closed) {
          reconnectTimer = window.setTimeout(connect, Math.min(1000 * 2 ** retries, 10000));
          retries += 1;
        }
      };
    };
    connect();

    const syncTimer = window.setInterval(() => {
      const socket = socketRef.current;
      if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "sync" }));
    }, SYNC_INTERVAL_MS);

    return () => {
      closed = true;
      window.clearTimeout(reconnectTimer);
      window.clearInterval(syncTimer);
      if (socketRef.current) socketRef.current.close();
    };
  }, [videoToken, instanceId, PROXY]);

  useEffect(() => {
    if (connected) { send({ type: "hello", name: userName, plays }); send({type:"browse"}); }
  }, [connected, plays, userName, send]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = window.setTimeout(() => setNotice(""), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  // --- Audio : le serveur fait foi, on recale seulement si l'écart dépasse la tolérance ---
  const applyAudio = useCallback(() => {
    const audio = audioRef.current;
    const current = stateRef.current;
    if (!audio || !current) return;
    const round = current.bt && current.bt.round;
    const inBlindTest = current.mode === "blindtest" && current.bt && current.bt.phase !== "final" && round;
    const wantedId = inBlindTest ? round.audio_id : current.mode === "karaoke" && current.karaoke.track ? current.karaoke.track.id : null;
    if (!wantedId) {
      if (!audio.paused) audio.pause();
      return;
    }
    if (audio.dataset.id !== wantedId) {
      audio.dataset.id = wantedId;
      audio.src = `${PROXY}/activity/karaoke/audio?t=${encodeURIComponent(videoToken)}&id=${encodeURIComponent(wantedId)}`;
      return; // onLoadedMetadata rappelle applyAudio une fois le fichier prêt
    }
    if (audio.readyState < 1 || !Number.isFinite(audio.duration)) return;

    const waited = (performance.now() - current.at) / 1000;
    let target;
    let shouldPlay;
    if (inBlindTest) {
      const base = round.start !== null && round.start !== undefined ? round.start : round.start_ratio * audio.duration;
      const start = Math.max(0, Math.min(base, Math.max(0, audio.duration - current.bt.seconds - 1)));
      target = start + round.elapsed + waited;
      shouldPlay = true;
    } else {
      target = current.karaoke.position + (current.karaoke.playing ? waited : 0);
      shouldPlay = current.karaoke.playing;
    }
    if (target >= audio.duration - 0.2) {
      if (!audio.paused) audio.pause();
      return;
    }
    if (Math.abs(audio.currentTime - target) > DRIFT_SECONDS) audio.currentTime = Math.max(0, target);
    if (shouldPlay && audio.paused) {
      audio.play().catch(() => setNeedsClick(true)); // autoplay refusé : un clic suffira
    } else if (!shouldPlay && !audio.paused) {
      audio.pause();
    }
  }, [videoToken, PROXY]);

  useEffect(() => {
    applyAudio();
  }, [state, applyAudio]);

  useEffect(() => {
    const timer = window.setInterval(applyAudio, 2000);
    return () => window.clearInterval(timer);
  }, [applyAudio]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = volume;
  }, [volume]);

  // --- Paroles : récupérées par le serveur (fichier .lrc, cache ou LRCLIB), jamais par le navigateur ---
  useEffect(() => {
    setLyrics({ status: trackId ? "loading" : "idle", lines: [] });
    setLyricsGate(null);
    if (!trackId) return undefined;
    const timer = window.setTimeout(() => setLyricsGate(trackId), 2500);
    return () => window.clearTimeout(timer);
  }, [trackId]);

  useEffect(() => {
    if (!trackId || lyricsGate !== trackId) return undefined;
    const controller = new AbortController();
    const params = new URLSearchParams({ t: videoToken, id: trackId });
    const audio = audioRef.current;
    if (audio && Number.isFinite(audio.duration) && audio.duration > 0) params.set("duration", String(Math.round(audio.duration)));
    fetch(`${PROXY}/activity/karaoke/lyrics?${params}`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error(String(response.status)))))
      .then((data) => setLyrics({ status: data.synced ? "ready" : "none", lines: data.lines || [] }))
      .catch((error) => {
        if (error.name !== "AbortError") setLyrics({ status: "error", lines: [] });
      });
    return () => controller.abort();
  }, [trackId, lyricsGate, videoToken, preparationRevision, PROXY]);

  const getTime = useCallback(() => (audioRef.current ? audioRef.current.currentTime : 0) + offset, [offset]);

  const changeOffset = (delta) => {
    const next = Math.round((offset + delta) * 100) / 100;
    setOffset(next);
    savePref("karaoke.offset", next);
  };

  const toggleRomaji = () => {
    setShowRomaji((value) => {
      savePref("karaoke.romaji", !value);
      return !value;
    });
  };

  const changeVolume = (value) => {
    setVolume(value);
    savePref("karaoke.volume", value);
  };

  const commitSeek = (raw) => {
    const target = Math.max(0, Math.min(Number(raw), duration || Number(raw)));
    setSeekPreview(null);
    if (!Number.isFinite(target)) return;
    if (audioRef.current) audioRef.current.currentTime = target;
    send({ type: "seek", position: target });
  };

  const audioElement = (
    <audio
      ref={audioRef}
      preload="auto"
      onLoadedMetadata={(event) => {
        setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0);
        setLyricsGate(event.currentTarget.dataset.id || null);
        applyAudio();
      }}
      onCanPlay={applyAudio}
      onTimeUpdate={(event) => {
        if (seekPreview === null) setPosition(event.currentTarget.currentTime);
      }}
      onEnded={(event) => {
        if (canControl && stateRef.current && stateRef.current.mode === "karaoke") {
          send({ type: "ended", id: event.currentTarget.dataset.id });
        }
      }}
    />
  );

  if (!state) {
    return (
      <div style={{ ...S.page, alignItems: "center", justifyContent: "center" }}>
        {audioElement}
        {connected ? "Chargement…" : "Connexion…"}
      </div>
    );
  }

  const lyricsMessage = {
    loading: "Recherche des paroles…",
    none: "Pas de paroles synchronisées pour ce titre (dépose un fichier .lrc à côté du morceau).",
    error: "Paroles indisponibles pour le moment.",
    idle: "Choisis un morceau pour commencer.",
  }[lyrics.status];

  return (
    <div style={S.page}>
      <KaraokeBackdrop audioRef={audioRef} theme={state.theme} playing={playing}/>
      <style>{KEYFRAMES}</style>
      {audioElement}

      <div style={S.top}>
        <span style={S.badge}>{mode === "blindtest" ? "🎯 Blind test" : "🎤 Karaoké"}</span>
        {!connected && <span style={S.badge}>Connexion…</span>}
        {mode === "karaoke" && track && (
          <span style={{ fontSize: 15, opacity: 0.9 }}>
            <strong>{track.title}</strong>
            {track.artist ? ` — ${track.artist}` : ""}
          </span>
        )}
        {notice && <span style={{ ...S.badge, background: "rgba(255,170,60,0.35)" }}>{notice}</span>}
        <span style={{ flex: 1 }} />
        <label style={{ fontSize: 13, display: "flex", gap: 6, alignItems: "center" }} title="Volume">
          🔊
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={volume}
            aria-label="Volume"
            style={{ accentColor: "#ff6ec4" }}
            onChange={(event) => changeVolume(Number(event.currentTarget.value))}
          />
        </label>
      </div>

      <KaraokeTools session={session} state={state} library={library} favorites={favorites} onPrepared={onPrepared} send={send} setLibrary={setLibrary} track={track} plays={plays} setPlays={setPlays}/>
      <div style={S.main}>
        {mode === "blindtest" && state.bt ? (
          <BlindTestView
            state={state}
            send={send}
            canControl={canControl}
            userId={userId}
            feedback={feedback}
            plays={plays}
            setPlays={setPlays}
            inputRef={inputRef}
          />
        ) : (
          <KaraokeLyrics lines={lyrics.lines} getTime={getTime} showRomaji={showRomaji} emptyLabel={lyricsMessage} />
        )}
      </div>

      {mode === "karaoke" && (
        <>
          {canControl && panel === "tracks" && (
            <div style={S.panel}>
              <div style={{ padding: "6px 10px", fontSize: 13, opacity: 0.7 }}>Choisir un morceau ({localTracks.length})</div>
              {localTracks.length === 0 && (
                <div style={{ padding: 10 }}>Aucun fichier audio dans le dossier. Le catalogue Deezer ne sert qu'au blind test (extraits de 30 s).</div>
              )}
              {localTracks.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  style={{ ...S.item, background: track && item.id === track.id ? "rgba(255,255,255,0.14)" : "transparent" }}
                  onClick={() => {
                    setPanel(null);
                    send({ type: "select", id: item.id });
                  }}
                >
                  <span>{track && item.id === track.id ? "▶ " : ""}{item.title}{item.artist ? ` — ${item.artist}` : ""}</span>
                  <span style={{ opacity: 0.6, fontSize: 12 }}>{item.lang ? item.lang.toUpperCase() : ""}</span>
                </button>
              ))}
            </div>
          )}
          {canControl && panel === "blindtest" && (
            <div style={{ ...S.panel, padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
              <div style={{ fontWeight: 800 }}>🎯 Lancer un blind test</div>
              <label style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                Morceaux
                <select
                  value={settings.pool}
                  style={{ padding: 6, borderRadius: 8, maxWidth: 260 }}
                  onChange={(event) => setSettings({ ...settings, pool: event.currentTarget.value })}
                >
                  <option value="all">Tout ({library.length})</option>
                  <option value="local">Mes fichiers ({localTracks.length})</option>
                  <option value="preview">Catalogue Deezer ({library.length - localTracks.length})</option>
                </select>
              </label>
              <label style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                Nombre de manches
                <input
                  type="number"
                  min="1"
                  max="50"
                  value={settings.rounds}
                  style={{ width: 80, padding: 6, borderRadius: 8 }}
                  onChange={(event) => setSettings({ ...settings, rounds: Number(event.currentTarget.value) })}
                />
              </label>
              <label style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
                Durée d'une manche (s)
                <input
                  type="number"
                  min="5"
                  max="90"
                  value={settings.seconds}
                  style={{ width: 80, padding: 6, borderRadius: 8 }}
                  onChange={(event) => setSettings({ ...settings, seconds: Number(event.currentTarget.value) })}
                />
              </label>
              {settings.pool !== "local" && settings.seconds > 28 && (
                <div style={{ fontSize: 12, opacity: 0.7 }}>Les extraits du catalogue durent 30 s : au-delà de ~28 s, la musique s'arrête avant la fin de la manche.</div>
              )}
              <label style={{ fontSize: 14, display: "flex", gap: 6, alignItems: "center" }}>
                <input type="checkbox" checked={plays} onChange={(event) => setPlays(event.target.checked)} />
                Je participe aussi
              </label>
              <button
                type="button"
                style={S.button}
                onClick={() => {
                  setPanel(null);
                  send({ type: "bt_start", rounds: settings.rounds, seconds: settings.seconds, pool: settings.pool });
                }}
              >
                Lancer la partie
              </button>
            </div>
          )}

          <div style={S.bar}>
            {canControl && (
              <div style={{ display: "grid", gridTemplateColumns: "48px minmax(120px, 1fr) 48px", alignItems: "center", gap: 10, fontSize: 13, fontVariantNumeric: "tabular-nums" }}>
                <span>{formatTime(seekPreview === null ? position : seekPreview)}</span>
                <input
                  aria-label="Position du morceau"
                  type="range"
                  min="0"
                  max={duration || 0}
                  step="0.1"
                  value={Math.min(seekPreview === null ? position : seekPreview, duration || 0)}
                  disabled={!duration}
                  style={{ width: "100%", accentColor: "#ff6ec4", cursor: "pointer" }}
                  onChange={(event) => setSeekPreview(Number(event.currentTarget.value))}
                  onPointerUp={(event) => commitSeek(event.currentTarget.value)}
                  onKeyUp={(event) => {
                    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) commitSeek(event.currentTarget.value);
                  }}
                />
                <span style={{ textAlign: "right" }}>{formatTime(duration)}</span>
              </div>
            )}
            <div style={S.row}>
              {canControl && (
                <>
                  <button type="button" style={S.button} disabled={!track} onClick={() => send({ type: playing ? "pause" : "play" })}>
                    {playing ? "⏸ Pause" : "▶ Lecture"}
                  </button>
                  <button type="button" style={S.button} onClick={() => setPanel(panel === "tracks" ? null : "tracks")}>
                    🎵 Morceaux
                  </button>
                  <button type="button" style={S.button} onClick={() => setPanel(panel === "blindtest" ? null : "blindtest")}>
                    🎯 Blind test
                  </button>
                  {onExit && (
                    <button type="button" style={S.ghost} onClick={onExit}>
                      🎞 Cinéma
                    </button>
                  )}
                </>
              )}
              <button type="button" style={S.ghost} onClick={toggleRomaji} aria-pressed={showRomaji} title="Afficher la romanisation au-dessus des paroles">
                {showRomaji ? "Romaji : oui" : "Romaji : non"}
              </button>

              <span style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }} title="Compense le décalage audio de ton appareil">
                Synchro
                <button type="button" style={S.ghost} onClick={() => changeOffset(-0.25)} aria-label="Paroles plus tard">−</button>
                <span style={{ minWidth: 44, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>{offset > 0 ? "+" : ""}{offset.toFixed(2)} s</span>
                <button type="button" style={S.ghost} onClick={() => changeOffset(0.25)} aria-label="Paroles plus tôt">+</button>
              </span>
            </div>
          </div>
        </>
      )}

      {needsClick && (
        <button
          type="button"
          style={S.overlay}
          onClick={() => {
            setNeedsClick(false);
            applyAudio();
          }}
        >
          ▶ Cliquer pour rejoindre la musique
        </button>
      )}
    </div>
  );
}
