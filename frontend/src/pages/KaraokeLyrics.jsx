import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

// Polices CJK en tête : l'Activity tourne dans le client Discord, qui utilise les polices du système.
export const LYRICS_FONT =
  '"Noto Sans JP","Noto Sans KR","Noto Sans SC","Hiragino Sans","Yu Gothic UI","Meiryo",' +
  '"Malgun Gothic","Microsoft YaHei",system-ui,sans-serif';

// Affichage inspiré des karaokés japonais (Joysound, DAM) :
// - deux lignes à positions fixes (haut à gauche, bas à droite) : on lit la suivante pendant qu'on chante ;
// - texte blanc à contour sombre qui se colore de gauche à droite, mot par mot, au rythme de la voix ;
// - romaji au-dessus de chaque mot, coloré en même temps que lui ;
// - compte à rebours « ● ● ● ● » avant une ligne qui suit un long passage instrumental.
const COUNTDOWN_SECONDS = 4;
const MIN_GAP_FOR_COUNTDOWN = 5;
const LINGER_AFTER_LINE = 0.45; // une ligne terminée laisse sa place à la suivante après ce délai

const CSS = `
.kl-root { position: relative; flex: 1; align-self: stretch; width: 100%; min-height: 0; overflow: hidden; }
.kl-bg { position: absolute; inset: 0; pointer-events: none; }
.kl-blob { position: absolute; width: 55vmax; height: 55vmax; border-radius: 50%; filter: blur(70px); opacity: 0.32; animation: klDrift 22s ease-in-out infinite; }
.kl-blob.a { background: #6a3cff; left: -15%; top: -25%; }
.kl-blob.b { background: #ff4f9a; right: -20%; bottom: -30%; animation-delay: -8s; opacity: 0.26; }
.kl-blob.c { background: #1fb6ff; left: 30%; top: 35%; animation-delay: -15s; opacity: 0.16; }
.kl-rows { position: absolute; inset: 0; z-index: 1; display: grid; grid-template-rows: minmax(0,1fr) minmax(0,1fr);
  gap: 12px; padding: 24px 5%; box-sizing: border-box; font-size: clamp(24px, 4.4vw, 52px); font-weight: 800; }
.kl-slot { display: flex; align-items: center; width: 100%; min-height: 0; }
.kl-slot.top { justify-content: flex-start; }
.kl-slot.bottom { justify-content: flex-end; }
.kl-line { position: relative; display: inline-block; width: max-content; flex-shrink: 0; line-height: 1.3; animation: klIn 260ms ease-out; }
.kl-slot.rom .kl-line { line-height: 2.05; }
.kl-text { white-space: nowrap; }
.kl-tok { position: relative; display: inline-block; white-space: pre; }
.kl-base, .kl-fill { -webkit-text-stroke-width: 0.13em; paint-order: stroke fill; stroke-linejoin: round; }
.kl-base { color: #fff; -webkit-text-stroke-color: #2b1d78; }
.kl-fill { position: absolute; left: 0; top: 0; color: #ff4f9a; -webkit-text-stroke-color: #fff;
  clip-path: inset(-1em calc(100% - var(--p, 0%)) -1em 0); }
.kl-tok ruby { display: inline-flex; flex-direction: column-reverse; align-items: center; vertical-align: bottom; padding-inline: .045em; ruby-align: center; }
.kl-tok rt { display: block; line-height: 1.25; padding-inline: .10em; text-align: center; white-space: pre; font-size: 0.4em; font-weight: 700; letter-spacing: 0.04em; -webkit-text-stroke-width: 0.16em; }
.kl-dots { position: absolute; left: 0; top: -0.7em; display: flex; gap: 0.22em; pointer-events: none; }
.kl-dots i { width: 0.34em; height: 0.34em; border-radius: 50%; background: #ff4f9a; border: 0.05em solid #fff;
  opacity: 0; transform: scale(0.4); transition: opacity 140ms ease, transform 140ms ease; }
.kl-dots i.on { opacity: 1; transform: scale(1); }
.kl-empty { opacity: 0.75; font-size: 18px; text-align: center; padding: 24px; font-weight: 500; }
@keyframes klIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes klDrift { 0%, 100% { transform: translate3d(-4%, -3%, 0) scale(1); } 50% { transform: translate3d(5%, 4%, 0) scale(1.14); } }
@media (prefers-reduced-motion: reduce) { .kl-blob, .kl-line { animation: none; } }
`;

// Lignes chantées uniquement (les pauses vides ne s'affichent pas), avec l'écart qui les précède.
function buildSung(lines) {
  const sung = [];
  for (const line of lines || []) {
    if (!line.tokens || line.tokens.length === 0) continue;
    const previous = sung[sung.length - 1];
    sung.push({ ...line, gap: previous ? line.t - previous.e : line.t });
  }
  return sung;
}

// Index de la dernière ligne dont le début est atteint (-1 avant la première).
function currentIndex(sung, time) {
  let low = 0;
  let high = sung.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (sung[mid].t <= time) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found;
}

// Les lignes paires vont en haut, les impaires en bas. La ligne qui vient de se terminer cède sa
// place à la ligne d'après-demain : le chanteur lit toujours deux lignes d'avance.
export function assignSlots(sung, time) {
  const count = sung.length;
  const current = currentIndex(sung, time);
  if (current < 0) return [count > 0 ? 0 : null, count > 1 ? 1 : null];
  const slots = [null, null];
  const finished = time > sung[current].e + LINGER_AFTER_LINE;
  slots[current % 2] = finished && current + 2 < count ? current + 2 : current;
  slots[1 - (current % 2)] = current + 1 < count ? current + 1 : null;
  return slots;
}

function Content({ token, showRomaji }) {
  const reading = showRomaji && token.r ? token.r : "";
  return reading ? (
    <ruby>
      {token.t}
      <rt>{reading}</rt>
    </ruby>
  ) : (
    token.t
  );
}

function Line({ line, showRomaji }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const element = ref.current, slot = element?.parentElement;
    if (!element || !slot) return;
    const fit = () => {
      element.style.fontSize = '52px';
      const naturalWidth = element.scrollWidth;
      const naturalHeight = element.getBoundingClientRect().height;
      if (!slot.clientWidth || !slot.clientHeight || !naturalWidth || !naturalHeight) return;
      const scale = Math.min(1, (slot.clientWidth-24)/naturalWidth, (slot.clientHeight-24)/naturalHeight);
      element.style.fontSize = `${Math.max(1, 52*scale)}px`;
    };
    fit();
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(fit) : null;
    observer?.observe(slot);
    document.fonts?.ready.then(fit);
    return () => observer?.disconnect();
  }, [line, showRomaji]);
  return (
    <div ref={ref} className="kl-line" data-start={line.t} data-gap={line.gap}>
      <div className="kl-dots" data-dots="">
        <i />
        <i />
        <i />
        <i />
      </div>
      <div className="kl-text">
        {line.tokens.map((token, i) => (
          <span key={i}>
            <span className="kl-tok" data-s={token.s} data-e={token.e}>
              <span className="kl-base">
                <Content token={token} showRomaji={showRomaji} />
              </span>
              <span className="kl-fill" aria-hidden="true">
                <Content token={token} showRomaji={showRomaji} />
              </span>
            </span>
            {token.sp ? " " : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

// Met à jour directement le DOM (sans re-rendu React) : remplissage des mots et compte à rebours.
function paint(root, time) {
  if (!root) return;
  root.querySelectorAll(".kl-line").forEach((lineElement) => {
    const remaining = Number(lineElement.dataset.start) - time;
    const gap = Number(lineElement.dataset.gap);
    const visible = gap >= MIN_GAP_FOR_COUNTDOWN && remaining > 0 && remaining <= COUNTDOWN_SECONDS ? Math.ceil(remaining) : 0;
    const dots = lineElement.querySelector("[data-dots]");
    if (dots && dots.dataset.n !== String(visible)) {
      dots.dataset.n = String(visible);
      Array.from(dots.children).forEach((dot, index) => dot.classList.toggle("on", index < visible));
    }
    lineElement.querySelectorAll(".kl-tok").forEach((element) => {
      const start = Number(element.dataset.s);
      const end = Number(element.dataset.e);
      let progress = 0;
      if (time >= end) progress = 100;
      else if (time > start) progress = ((time - start) / Math.max(end - start, 0.01)) * 100;
      const fill = element.lastElementChild;
      if (fill) fill.style.setProperty("--p", `${progress.toFixed(1)}%`);
    });
  });
}

/**
 * Paroles synchronisées façon karaoké japonais. `getTime()` renvoie la position de lecture (secondes) ;
 * la boucle d'animation ne re-rend React que lorsqu'une ligne change de place.
 */
export default function KaraokeLyrics({ lines, getTime, showRomaji, emptyLabel }) {
  const sung = useMemo(() => buildSung(lines), [lines]);
  const [slots, setSlots] = useState([null, null]);
  const rootRef = useRef(null);

  useEffect(() => {
    setSlots([null, null]);
    if (sung.length === 0) return undefined;
    let frame = 0;
    const tick = () => {
      const time = getTime();
      const next = assignSlots(sung, time);
      setSlots((previous) => (previous[0] === next[0] && previous[1] === next[1] ? previous : next));
      paint(rootRef.current, time);
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [sung, getTime]);

  if (sung.length === 0) {
    return (
      <div className="kl-root">
        <style>{CSS}</style>
        <div className="kl-bg">
          <div className="kl-blob a" />
          <div className="kl-blob b" />
        </div>
        <div style={{ position: "relative", zIndex: 1, height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="kl-empty">{emptyLabel}</div>
        </div>
      </div>
    );
  }

  const slotClass = (position) => `kl-slot ${position}${showRomaji ? " rom" : ""}`;
  return (
    <div className="kl-root" ref={rootRef}>
      <style>{CSS}</style>
      <div className="kl-bg">
        <div className="kl-blob a" />
        <div className="kl-blob b" />
        <div className="kl-blob c" />
      </div>
      <div className="kl-rows">
        <div className={slotClass("top")}>
          {slots[0] !== null && <Line key={`${slots[0]}-${showRomaji}`} line={sung[slots[0]]} showRomaji={showRomaji} />}
        </div>
        <div className={slotClass("bottom")}>
          {slots[1] !== null && <Line key={`${slots[1]}-${showRomaji}`} line={sung[slots[1]]} showRomaji={showRomaji} />}
        </div>
      </div>
    </div>
  );
}
