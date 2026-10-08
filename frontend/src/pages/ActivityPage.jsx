import { useCallback, useEffect, useRef, useState } from "react";
import { DiscordSDK } from "@discord/embedded-app-sdk";

// Dans l'iframe Discord, le domaine est .discordsays.com : on peut donc
// retrouver le client id sans variable de build. REACT_APP_DISCORD_CLIENT_ID est facultatif.
const CLIENT_ID =
  process.env.REACT_APP_DISCORD_CLIENT_ID || window.location.hostname.split(".")[0];

// "/backend" est le préfixe déclaré dans les URL Mappings du portail Discord
// (cible : api.loasis.app). Tout appel réseau d'une Activity doit passer par /.proxy.
const PROXY = "/.proxy/backend/api";

// Écart toléré avant de recaler la vidéo sur la position du serveur.
const DRIFT_PLAYING = 2; // secondes, en lecture
const DRIFT_PAUSED = 0.5; // secondes, en pause
const SYNC_INTERVAL_MS = 5000;
const CONTROLS_HIDE_MS = 3000;

const styles = {
  page: {
    position: "relative",
    background: "#000",
    color: "#fff",
    width: "100vw",
    height: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontFamily: "system-ui, sans-serif",
    overflow: "hidden",
  },
  video: { width: "100%", height: "100%", background: "#000" },
  overlay: {
    position: "absolute",
    inset: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "rgba(0,0,0,0.6)",
    cursor: "pointer",
    fontSize: 20,
    border: "none",
    color: "#fff",
    width: "100%",
  },
  badge: {
    position: "absolute",
    top: 12,
    left: 12,
    padding: "6px 12px",
    borderRadius: 999,
    background: "rgba(0,0,0,0.7)",
    fontSize: 14,
  },
  controlBar: {
    position: "absolute",
    bottom: 20,
    left: "50%",
    transform: "translateX(-50%)",
    width: "min(760px, calc(100vw - 32px))",
    display: "flex",
    flexDirection: "column",
    gap: 10,
    padding: 12,
    borderRadius: 14,
    background: "rgba(0,0,0,0.72)",
    transition: "opacity 180ms ease",
  },
  seekRow: {
    display: "grid",
    gridTemplateColumns: "64px minmax(120px, 1fr) 64px",
    alignItems: "center",
    gap: 10,
    fontSize: 13,
    fontVariantNumeric: "tabular-nums",
  },
  seekInput: { width: "100%", accentColor: "#fff", cursor: "pointer" },
  buttonRow: { display: "flex", justifyContent: "center", gap: 10 },
  controlButton: {
    padding: "10px 24px",
    borderRadius: 999,
    border: "none",
    background: "rgba(255,255,255,0.92)",
    color: "#111",
    fontSize: 16,
    fontWeight: 600,
    cursor: "pointer",
  },
  panel: {
    position: "absolute",
    bottom: 132,
    left: "50%",
    transform: "translateX(-50%)",
    width: "min(480px, 92vw)",
    maxHeight: "50vh",
    overflowY: "auto",
    padding: 8,
    borderRadius: 12,
    background: "rgba(20,20,24,0.96)",
    border: "1px solid rgba(255,255,255,0.15)",
    transition: "opacity 180ms ease",
  },
  panelTitle: { padding: "6px 10px", fontSize: 13, opacity: 0.7 },
  videoItem: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    width: "100%",
    padding: "10px 12px",
    border: "none",
    borderRadius: 8,
    background: "transparent",
    color: "#fff",
    fontSize: 15,
    textAlign: "left",
    cursor: "pointer",
  },
  videoItemActive: { background: "rgba(255,255,255,0.14)", fontWeight: 600 },
};

const MESSAGES = {
  loading: "Chargement…",
  forbidden: "Cette activité est réservée aux membres du serveur.",
  error: "Impossible de charger la vidéo. Réessaie dans un instant.",
};

function describeError(error) {
  if (!error) return "erreur inconnue";
  if (typeof error === "string") return error;
  if (error.message) return error.code ? `${error.code} - ${error.message}` : error.message;
  try {
    return JSON.stringify(error);
  } catch (e) {
    return String(error);
  }
}

function formatSize(bytes) {
  if (!bytes) return "";
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} Go` : `${Math.round(mb)} Mo`;
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}

export default function ActivityPage() {
  const [session, setSession] = useState({ status: "loading" });
  const [playing, setPlaying] = useState(true);
  const [connected, setConnected] = useState(false);
  const [needsClick, setNeedsClick] = useState(false);
  const [videos, setVideos] = useState([]);
  const [currentVideo, setCurrentVideo] = useState(null);
  const [videoVersion, setVideoVersion] = useState(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [seekPreview, setSeekPreview] = useState(null);

  const videoRef = useRef(null);
  const socketRef = useRef(null);
  const controlsTimerRef = useRef(null);
  const controlsHoveredRef = useRef(false);
  // Dernier état reçu du serveur : { playing, position }
  const serverState = useRef({ playing: true, position: 0 });

  const clearControlsTimer = useCallback(() => {
    if (controlsTimerRef.current) {
      window.clearTimeout(controlsTimerRef.current);
      controlsTimerRef.current = null;
    }
  }, []);

  const scheduleControlsHide = useCallback(() => {
    clearControlsTimer();
    controlsTimerRef.current = window.setTimeout(() => {
      if (!controlsHoveredRef.current) {
        setControlsVisible(false);
        setPickerOpen(false);
      }
    }, CONTROLS_HIDE_MS);
  }, [clearControlsTimer]);

  const revealControls = useCallback(() => {
    setControlsVisible(true);
    scheduleControlsHide();
  }, [scheduleControlsHide]);

  const holdControls = () => {
    controlsHoveredRef.current = true;
    setControlsVisible(true);
    clearControlsTimer();
  };

  const releaseControls = () => {
    controlsHoveredRef.current = false;
    scheduleControlsHide();
  };

  useEffect(() => {
    scheduleControlsHide();
    return clearControlsTimer;
  }, [scheduleControlsHide, clearControlsTimer]);

  // Aligne la vidéo locale sur l'état du serveur. Le serveur fait foi : seuls les
  // membres staff munis du droit signé peuvent modifier la position partagée.
  const applyState = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const { playing: shouldPlay, position: serverPosition } = serverState.current;
    setPosition(serverPosition);

    // Fin de vidéo : on reste sur la dernière image, sans relancer depuis le début.
    if (video.duration && serverPosition >= video.duration - 0.3) {
      video.pause();
      return;
    }

    const tolerance = shouldPlay ? DRIFT_PLAYING : DRIFT_PAUSED;
    if (Math.abs(video.currentTime - serverPosition) > tolerance) {
      video.currentTime = serverPosition;
    }

    if (shouldPlay && video.paused) {
      video.play().catch(() => setNeedsClick(true)); // autoplay refusé : un clic suffira
    } else if (!shouldPlay && !video.paused) {
      video.pause();
    }
  }, []);

  // 1) Authentification Discord + vérification du serveur
  useEffect(() => {
    let cancelled = false;

    (async () => {
      let step = "init";
      try {
        step = "sdk";
        const sdk = new DiscordSDK(CLIENT_ID);
        step = "ready";
        await sdk.ready();

        step = "authorize";
        const { code } = await sdk.commands.authorize({
          client_id: CLIENT_ID,
          response_type: "code",
          state: "",
          prompt: "none",
          scope: ["identify", "guilds.members.read"],
        });

        step = "token";
        const response = await fetch(`${PROXY}/activity/token`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, guild_id: sdk.guildId }),
        });
        if (!response.ok) {
          let body = "";
          try {
            body = await response.text();
          } catch (e) {
            body = "";
          }
          const failure = new Error(`HTTP ${response.status} ${body}`);
          failure.httpStatus = response.status;
          throw failure;
        }
        const data = await response.json();

        step = "authenticate";
        await sdk.commands.authenticate({ access_token: data.access_token });

        if (!cancelled) {
          setVideoVersion(data.video_version);
          setSession({
            status: "ok",
            title: data.title,
            canControl: data.can_control,
            videoToken: data.video_token,
            instanceId: sdk.instanceId,
          });
        }
      } catch (error) {
        const detail = `[${step}] ${describeError(error)}`;
        console.error("[activity] échec", detail, error);
        if (!cancelled) {
          setSession({
            status: error && error.httpStatus === 403 ? "forbidden" : "error",
            detail,
          });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // 2) Connexion WebSocket de synchronisation (avec reconnexion automatique)
  useEffect(() => {
    if (session.status !== "ok") return undefined;

    let closed = false;
    let retries = 0;
    let reconnectTimer;

    const connect = () => {
      const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      const query = new URLSearchParams({
        t: session.videoToken,
        instance_id: session.instanceId,
      });
      const socket = new WebSocket(
        `${scheme}//${window.location.host}${PROXY}/activity/ws?${query}`
      );
      socketRef.current = socket;

      socket.onopen = () => {
        retries = 0;
        setConnected(true);
      };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "video_changed") {
          // Change uniquement la source vidéo : recharger toute l'iframe casse parfois
          // le handshake entre l'Activity et le client Discord.
          const nextPlaying = typeof message.playing === "boolean" ? message.playing : true;
          serverState.current = { playing: nextPlaying, position: 0 };
          setPlaying(nextPlaying);
          setPosition(0);
          setSeekPreview(null);
          setNeedsClick(false);
          setCurrentVideo(message.current || null);
          setSession((current) => ({
            ...current,
            title: message.title || current.title,
          }));
          setVideoVersion(message.video_version);
          return;
        }
        if (message.type === "videos") {
          setVideos(message.videos || []);
          setCurrentVideo(message.current || null);
          return;
        }
        if (message.type !== "state") return;
        serverState.current = { playing: message.playing, position: message.position };
        setPlaying(message.playing);
        setPosition(message.position);
        applyState();
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

    // Demande régulièrement l'état au serveur : recale la vidéo après une coupure ou du buffering,
    // et évite que le proxy ferme une connexion inactive.
    const syncTimer = window.setInterval(() => {
      const socket = socketRef.current;
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "sync" }));
      }
    }, SYNC_INTERVAL_MS);

    return () => {
      closed = true;
      window.clearTimeout(reconnectTimer);
      window.clearInterval(syncTimer);
      socketRef.current?.close();
    };
  }, [session.status, session.videoToken, session.instanceId, applyState]);

  const send = (payload) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }
  };

  const sendControl = () => {
    revealControls();
    send({ type: playing ? "pause" : "play" });
  };

  const commitSeek = (rawValue) => {
    const requested = Number(rawValue);
    if (!Number.isFinite(requested)) return;
    const target = Math.max(0, Math.min(requested, duration || requested));
    serverState.current = { ...serverState.current, position: target };
    setPosition(target);
    setSeekPreview(null);
    if (videoRef.current) videoRef.current.currentTime = target;
    send({ type: "seek", position: target });
    revealControls();
  };

  const togglePicker = () => {
    revealControls();
    if (!pickerOpen) send({ type: "list" }); // rafraîchit la liste des fichiers du dossier
    setPickerOpen((open) => !open);
  };

  const chooseVideo = (name) => {
    revealControls();
    setPickerOpen(false);
    if (name !== currentVideo) send({ type: "select", name });
  };

  const startPlayback = () => {
    setNeedsClick(false);
    applyState();
  };

  if (session.status !== "ok") {
    return (
      <div style={styles.page}>
        <div style={{ textAlign: "center", maxWidth: 640, padding: 16 }}>
          <div>{MESSAGES[session.status]}</div>
          {session.detail && (
            <pre style={{ fontSize: 12, opacity: 0.7, whiteSpace: "pre-wrap" }}>{session.detail}</pre>
          )}
        </div>
      </div>
    );
  }

  const videoSrc =
    `${PROXY}/activity/video?t=${encodeURIComponent(session.videoToken)}` +
    `&v=${videoVersion ?? "initial"}`;

  return (
    <div
      style={styles.page}
      onContextMenu={(event) => event.preventDefault()}
      onMouseMove={revealControls}
      onPointerDown={revealControls}
    >
      <video
        ref={videoRef}
        src={videoSrc}
        title={session.title}
        style={styles.video}
        playsInline
        preload="auto"
        disablePictureInPicture
        controlsList="nodownload noremoteplayback"
        onLoadedMetadata={(event) => {
          const nextDuration = event.currentTarget.duration;
          setDuration(Number.isFinite(nextDuration) ? nextDuration : 0);
          applyState();
        }}
        onDurationChange={(event) => {
          const nextDuration = event.currentTarget.duration;
          setDuration(Number.isFinite(nextDuration) ? nextDuration : 0);
        }}
        onTimeUpdate={(event) => {
          if (seekPreview === null) setPosition(event.currentTarget.currentTime);
        }}
        onCanPlay={applyState}
        onPause={() => {
          if (serverState.current.playing) applyState();
        }}
      />

      {!connected && <div style={styles.badge}>Connexion…</div>}
      {connected && !playing && <div style={styles.badge}>⏸ En pause</div>}

      {session.canControl && connected && pickerOpen && (
        <div
          style={{
            ...styles.panel,
            opacity: controlsVisible ? 1 : 0,
            pointerEvents: controlsVisible ? "auto" : "none",
          }}
          onMouseEnter={holdControls}
          onMouseLeave={releaseControls}
        >
          <div style={styles.panelTitle}>Choisir la vidéo ({videos.length})</div>
          {videos.length === 0 && <div style={styles.panelTitle}>Aucun fichier dans le dossier.</div>}
          {videos.map((video) => (
            <button
              key={video.name}
              type="button"
              style={{
                ...styles.videoItem,
                ...(video.name === currentVideo ? styles.videoItemActive : {}),
              }}
              onClick={() => chooseVideo(video.name)}
            >
              <span>{video.name === currentVideo ? "▶ " : ""}{video.title}</span>
              <span style={{ opacity: 0.6, fontSize: 12 }}>{formatSize(video.size)}</span>
            </button>
          ))}
        </div>
      )}

      {session.canControl && connected && (
        <div
          style={{
            ...styles.controlBar,
            opacity: controlsVisible ? 1 : 0,
            pointerEvents: controlsVisible ? "auto" : "none",
          }}
          onMouseEnter={holdControls}
          onMouseLeave={releaseControls}
          onFocus={holdControls}
          onBlur={releaseControls}
        >
          <div style={styles.seekRow}>
            <span>{formatTime(seekPreview ?? position)}</span>
            <input
              aria-label="Position de la vidéo"
              type="range"
              min="0"
              max={duration || 0}
              step="0.1"
              value={Math.min(seekPreview ?? position, duration || 0)}
              disabled={!duration}
              style={styles.seekInput}
              onChange={(event) => setSeekPreview(Number(event.currentTarget.value))}
              onPointerUp={(event) => commitSeek(event.currentTarget.value)}
              onPointerCancel={() => setSeekPreview(null)}
              onKeyUp={(event) => {
                if (["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(event.key)) {
                  commitSeek(event.currentTarget.value);
                }
              }}
            />
            <span style={{ textAlign: "right" }}>{formatTime(duration)}</span>
          </div>
          <div style={styles.buttonRow}>
            <button type="button" style={styles.controlButton} onClick={sendControl}>
              {playing ? "⏸ Pause" : "▶ Reprendre"}
            </button>
            <button type="button" style={styles.controlButton} onClick={togglePicker}>
              🎞 Vidéos
            </button>
          </div>
        </div>
      )}

      {needsClick && (
        <button type="button" style={styles.overlay} onClick={startPlayback}>
          ▶ Cliquer pour rejoindre la lecture
        </button>
      )}
    </div>
  );
}
