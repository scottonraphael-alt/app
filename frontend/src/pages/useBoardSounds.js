import { useEffect, useRef, useState } from "react";

const SOUND_PREFERENCE = "oasisgame.board-sounds";
const SOUNDS = {
  codenames: [[0,0.07,440,320,0.025,"triangle"],[0.065,0.10,660,520,0.02,"sine"]],
  uno: [[0,0.065,680,420,0.025,"triangle"],[0.06,0.07,880,660,0.02,"sine"]],
  minesweeper: [[0, 0.05, 540, 430, 0.025, "sine"], [0.03, 0.06, 760, 610, 0.018, "triangle"]],
  scrabble: [[0, 0.07, 610, 390, 0.035, "triangle"], [0.07, 0.09, 820, 600, 0.025, "sine"]],
  connect_four: [
    [0, 0.065, 480, 220, 0.035, "sine"],
    [0.065, 0.07, 295, 135, 0.045, "sine"],
    [0.13, 0.10, 155, 78, 0.09, "triangle"],
  ],
  tic_tac_toe: [
    [0, 0.09, 640, 330, 0.055, "triangle"],
    [0.02, 0.10, 420, 200, 0.03, "sine"],
  ],
};

function playSound(context, mode) {
  for (const [delay, duration, pitch, endPitch, volume, type] of SOUNDS[mode]) {
    const start = context.currentTime + delay;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(pitch, start);
    oscillator.frequency.exponentialRampToValueAtTime(endPitch, start + duration);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(volume, start + 0.009);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.onended = () => gain.disconnect();
    oscillator.start(start);
    oscillator.stop(start + duration);
  }
}

export function useBoardSounds(mode, roundId, ply, connected) {
  const context = useRef(null);
  const previous = useRef(null);
  const [enabled, setEnabled] = useState(() => {
    try { return localStorage.getItem(SOUND_PREFERENCE) !== "off"; } catch { return true; }
  });

  function unlock() {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return;
    try {
      if (!context.current) context.current = new Audio();
      if (context.current.state === "suspended") context.current.resume().catch(() => {});
    } catch {
      // Browsers may deny sound inside an embedded Activity.
    }
  }

  function toggle() {
    if (!enabled) unlock();
    setEnabled(!enabled);
    try { localStorage.setItem(SOUND_PREFERENCE, enabled ? "off" : "on"); } catch { /* Optional preference. */ }
  }

  useEffect(() => {
    const last = previous.current;
    previous.current = { roundId, ply, connected };
    if (enabled && connected && last?.connected && roundId && last.roundId === roundId &&
        ply === last.ply + 1 && context.current?.state === "running") {
      playSound(context.current, mode);
    }
  }, [connected, enabled, mode, ply, roundId]);

  useEffect(() => () => {
    context.current?.close().catch(() => {});
    context.current = null;
  }, []);

  return { enabled, toggle, unlock };
}
