import { useEffect, useRef, useState } from "react";

// Polices CJK en tête : l'Activity tourne dans le client Discord, qui utilise les polices du système.
export const LYRICS_FONT =
  '"Noto Sans JP","Noto Sans KR","Noto Sans SC","Hiragino Sans","Yu Gothic UI","Meiryo",' +
  '"Malgun Gothic","Microsoft YaHei",system-ui,sans-serif';

const ACCENT = "#ff6ec4";
const IDLE = "rgba(255,255,255,0.55)";

// Index de la dernière ligne dont le début est atteint (-1 avant la première).
function findLine(lines, time) {
  let low = 0;
  let high = lines.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (lines[mid].t <= time) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found;
}

const fillStyle = {
  backgroundImage: "linear-gradient(90deg, var(--on) var(--p), var(--off) var(--p))",
  WebkitBackgroundClip: "text",
  backgroundClip: "text",
  WebkitTextFillColor: "transparent",
  color: "transparent",
};

function Token({ token, showRomaji, karaoke }) {
  const reading = showRomaji && token.r ? token.r : "";
  const content = reading ? (
    <ruby>
      {token.t}
      <rt style={{ fontSize: "0.42em", letterSpacing: "0.04em", fontWeight: 500 }}>{reading}</rt>
    </ruby>
  ) : (
    token.t
  );
  if (!karaoke) return <span>{content}{token.sp ? " " : ""}</span>;
  return (
    <span
      data-tok=""
      data-s={token.s}
      data-e={token.e}
      style={{ ...fillStyle, "--on": ACCENT, "--off": "#fff", "--p": "0%" }}
    >
      {content}
      {token.sp ? " " : ""}
    </span>
  );
}

function Line({ line, role, showRomaji }) {
  const sizes = { prev: "clamp(16px, 2.4vw, 26px)", current: "clamp(28px, 5vw, 58px)", next: "clamp(20px, 3.2vw, 36px)", later: "clamp(16px, 2.4vw, 26px)" };
  const opacity = { prev: 0.3, current: 1, next: 0.6, later: 0.3 }[role];
  const tokens = line.tokens || [];
  return (
    <div
      style={{
        fontSize: sizes[role],
        opacity,
        fontWeight: role === "current" ? 800 : 600,
        lineHeight: showRomaji ? 2.1 : 1.45,
        textAlign: "center",
        color: role === "current" ? "#fff" : IDLE,
        transition: "opacity 220ms ease, font-size 220ms ease",
        padding: "0 16px",
        textShadow: "0 2px 18px rgba(0,0,0,0.55)",
        minHeight: "1.5em",
      }}
    >
      {tokens.length === 0 ? (
        <span style={{ letterSpacing: "0.4em", opacity: 0.7 }}>♪ ♪ ♪</span>
      ) : (
        tokens.map((token, i) => (
          <Token key={`${line.t}-${i}`} token={token} showRomaji={showRomaji} karaoke={role === "current"} />
        ))
      )}
    </div>
  );
}

/**
 * Paroles synchronisées : ligne en cours remplie mot par mot, romaji au-dessus de chaque mot.
 * `getTime()` renvoie la position de lecture (secondes) ; la boucle d'animation ne re-rend React
 * que lors d'un changement de ligne et met à jour la progression des mots directement dans le DOM.
 */
export default function KaraokeLyrics({ lines, getTime, showRomaji, emptyLabel }) {
  const [index, setIndex] = useState(-1);
  const currentRef = useRef(null);

  useEffect(() => {
    setIndex(-1);
    if (!lines || lines.length === 0) return undefined;
    let frame = 0;
    const tick = () => {
      const time = getTime();
      const next = findLine(lines, time);
      setIndex((previous) => (previous === next ? previous : next));
      const root = currentRef.current;
      if (root) {
        root.querySelectorAll("[data-tok]").forEach((element) => {
          const start = Number(element.dataset.s);
          const end = Number(element.dataset.e);
          let progress = 0;
          if (time >= end) progress = 100;
          else if (time > start) progress = ((time - start) / Math.max(end - start, 0.01)) * 100;
          element.style.setProperty("--p", `${progress.toFixed(1)}%`);
        });
      }
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [lines, getTime]);

  if (!lines || lines.length === 0) {
    return <div style={{ opacity: 0.7, fontSize: 18, textAlign: "center", padding: 24 }}>{emptyLabel}</div>;
  }

  // Avant la première ligne, on montre les deux premières en aperçu.
  const current = index >= 0 ? lines[index] : null;
  const upcoming = lines.slice(index + 1, index + 3);
  const previous = index > 0 ? lines[index - 1] : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 14, width: "100%" }}>
      {previous && <Line line={previous} role="prev" showRomaji={showRomaji} />}
      {current ? (
        <div ref={currentRef} style={{ width: "100%" }}>
          <Line key={current.t} line={current} role="current" showRomaji={showRomaji} />
        </div>
      ) : (
        <div style={{ height: "1.5em" }} />
      )}
      {upcoming[0] && <Line line={upcoming[0]} role="next" showRomaji={showRomaji} />}
      {upcoming[1] && <Line line={upcoming[1]} role="later" showRomaji={showRomaji} />}
    </div>
  );
}
