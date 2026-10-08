import { useCallback, useEffect, useRef, useState } from "react";
import { DiscordSDK } from "@discord/embedded-app-sdk";

// Dans l'iframe Discord, le domaine est <client_id>.discordsays.com : on peut donc
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
  controlButton: {
    position: "absolute",
    bottom: 20,
    left: "50%",
    transform: "translateX(-50%)",
    padding: "10px 24px",
    borderRadius: 999,
    border: "none",
    background: "rgba(255,255,255,0.92)",
    color: "#111",
    fontSize: 16,
    fontWeight: 600,
    cursor: "pointer",
  },
};

const MESSAGES = {
  loading: "Chargement…",
  forbidden: "Cette activité est réservée aux membres du serveur.",
  error: "Impossible de charger la vidéo. Réessaie dans un instant.",
};

export default function ActivityPage() {
  const [session, setSession] = useState({ status: "loading" });
  const [playing, setPlaying] = useState(true);
  const [connected, setConnected] = useState(false);
  const [needsClick, setNeedsClick] = useState(false);

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
      try {
        const sdk = new DiscordSDK(CLIENT_ID);
        await sdk.ready();

        const { code } = await sdk.commands.authorize({
          client_id: CLIENT_ID,
          response_type: "code",
          state: "",
          prompt: "none",
          scope: ["identify"],
        });

        const response = await fetch(`${PROXY}/activity/token`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, guild_id: sdk.guildId }),
        });
        if (!response.ok) {
          throw new Error(response.status === 403 ? "forbidden" : "error");
        }

        const data = await response.json();
        await sdk.commands.authenticate({ access_token: data.access_token });

        if (!cancelled) {
          setSession({
            status: "ok",
            title: data.title,
            canControl: data.can_control,
            videoToken: data.video_token,
            instanceId: sdk.instanceId,
          });
        }
      } catch (error) {
        if (!cancelled) {
          setSession({ status: error.message === "forbidden" ? "forbidden" : "error" });
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

  const sendControl = () => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: playing ? "pause" : "play" }));
    }
  };

  const startPlayback = () => {
    setNeedsClick(false);
    applyState();
  };

  if (session.status !== "ok") {
    return <div style={styles.page}>{MESSAGES[session.status]}</div>;
  }

  return (
    <div style={styles.page} onContextMenu={(event) => event.preventDefault()}>
      <video
        ref={videoRef}
        style={styles.video}
        src={`${PROXY}/activity/video?t=${encodeURIComponent(session.videoToken)}`}
        title={session.title}
        playsInline
        preload="auto"
        // Pas d'attribut "controls" : aucune barre de progression, donc personne ne peut avancer ou reculer.
        controlsList="nodownload noplaybackrate"
        disablePictureInPicture
        onLoadedMetadata={applyState}
        // Si quelque chose met la vidéo en pause alors que le serveur dit "lecture", on relance.
        onPause={() => {
          if (serverState.current.playing) applyState();
        }}
      />

      {!connected && <div style={styles.badge}>Connexion…</div>}
      {connected && !playing && <div style={styles.badge}>⏸ En pause</div>}

      {session.canControl && connected && (
        <button type="button" style={styles.controlButton} onClick={sendControl}>
          {playing ? "⏸ Pause" : "▶ Reprendre"}
        </button>
      )}

      {needsClick && (
        <button type="button" style={styles.overlay} onClick={startPlayback}>
          ▶ Cliquer pour rejoindre la lecture
        </button>
      )}
    </div>
  );
}
