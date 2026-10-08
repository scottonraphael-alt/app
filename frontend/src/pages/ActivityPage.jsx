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
    display: "flex",
    gap: 10,
  },
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
    bottom: 76,
    left: "50%",
    transform: "translateX(-50%)",
    width: "min(480px, 92vw)",
    maxHeight: "50vh",
    overflowY: "auto",
    padding: 8,
    borderRadius: 12,
    background: "rgba(20,20,24,0.96)",
    border: "1px solid rgba(255,255,255,0.15)",
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

export default function ActivityPage() {
  const [session, setSession] = useState({ status: "loading" });
  const [playing, setPlaying] = useState(true);
  const [connected, setConnected] = useState(false);
  const [needsClick, setNeedsClick] = useState(false);
  const [videos, setVideos] = useState([]);
  const [currentVideo, setCurrentVideo] = useState(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const videoRef = useRef(null);
  const socketRef = useRef(null);
  // Dernier état reçu du serveur : { playing, position }
  const serverState = useRef({ playing: true, position: 0 });

  // Aligne la vidéo locale sur l'état du serveur. Le serveur fait foi : l'utilisateur
  // n'a aucun moyen de choisir la position (pas de barre de progression).
  const applyState = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    const { playing: shouldPlay, position } = serverState.current;

    // Fin de vidéo : on reste sur la dernière image, sans relancer depuis le début.
    if (video.duration && position >= video.duration - 0.3) {
      video.pause();
      return;
    }

    const tolerance = shouldPlay ? DRIFT_PLAYING : DRIFT_PAUSED;
    if (Math.abs(video.currentTime - position) > tolerance) {
      video.currentTime = position;
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
          setSession({
            status: "ok",
            title: data.title,
            canControl: data.can_control,
            videoToken: data.video_token,
            videoVersion: data.video_version,
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
        if (message.type === "reload") {
          // Le staff a changé de vidéo : on recharge pour récupérer la nouvelle.
          window.location.reload();
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
  }, [session, applyState]);

  const send = (payload) => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }
  };

  const sendControl = () => send({ type: playing ? "pause" : "play" });

  const togglePicker = () => {
    if (!pickerOpen) send({ type: "list" }); // rafraîchit la liste des fichiers du dossier
    setPickerOpen((open) => !open);
  };

  const chooseVideo = (name) => {
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
    `&v=${session.videoVersion}`;

  return (
    <div style={styles.page} onContextMenu={(event) => event.preventDefault()}>
      <video
        ref={videoRef}
        src={videoSrc}
        title={session.title}
        style={styles.video}
        playsInline
        preload="auto"
        disablePictureInPicture
        controlsList="nodownload noremoteplayback"
        onLoadedMetadata={applyState}
        onCanPlay={applyState}
        onPause={() => {
          if (serverState.current.playing) applyState();
        }}
      />

      {!connected && <div style={styles.badge}>Connexion…</div>}
      {connected && !playing && <div style={styles.badge}>⏸ En pause</div>}

      {session.canControl && connected && pickerOpen && (
        <div style={styles.panel}>
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
        <div style={styles.controlBar}>
          <button type="button" style={styles.controlButton} onClick={sendControl}>
            {playing ? "⏸ Pause" : "▶ Reprendre"}
          </button>
          <button type="button" style={styles.controlButton} onClick={togglePicker}>
            🎞 Vidéos
          </button>
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
