import { useEffect, useRef } from "react";
import { useReducedMotion } from "./Motion";

const SELECTOR = "[data-iris-reveal]";
const EASE = "cubic-bezier(.22,1,.36,1)";
const EFFECTS = {
  card: {
    duration: 440,
    frames: [
      { opacity: .64, translate: "0 15px" },
      { opacity: 1, translate: "0 -2px", offset: .78 },
      { opacity: 1, translate: "0 0" },
    ],
  },
  message: {
    duration: 340,
    frames: [
      { opacity: .6, translate: "-12px 4px", scale: ".985" },
      { opacity: 1, translate: "0 0", scale: "1" },
    ],
  },
  agenda: {
    duration: 320,
    frames: [
      { opacity: .62, translate: "0 8px" },
      { opacity: 1, translate: "0 0" },
    ],
  },
  badge: {
    duration: 360,
    frames: [
      { opacity: .65, scale: ".8", rotate: "-6deg" },
      { opacity: 1, scale: "1.05", rotate: "1deg", offset: .78 },
      { opacity: 1, scale: "1", rotate: "0deg" },
    ],
  },
  meter: {
    duration: 540,
    frames: [{ scale: "0 1" }, { scale: "1 1" }],
  },
};

export default function useSurfaceMotion(ref) {
  const reduced = useReducedMotion();
  const revealed = useRef(new WeakSet());
  useEffect(() => {
    const root = ref.current;
    if (!root || reduced || typeof IntersectionObserver === "undefined") return;

    const pending = new Set();
    const seen = revealed.current;
    const running = new Set();
    const viewport = new IntersectionObserver(entries => {
      const groups = new Map();
      for (const entry of entries) {
        if (!entry.isIntersecting || !pending.has(entry.target)) continue;
        const element = entry.target;
        viewport.unobserve(element);
        pending.delete(element);
        seen.add(element);
        if (element.closest("[inert], [hidden]") || element.parentElement?.closest("[aria-hidden='true']") || !element.animate) continue;
        if (element.contains(document.activeElement)) continue;

        const effect = EFFECTS[element.dataset.irisReveal];
        if (!effect) continue;
        const index = groups.get(element.parentElement) ?? 0;
        if (index >= 5) continue;
        groups.set(element.parentElement, index + 1);

        const animation = element.animate(effect.frames, {
          duration: effect.duration,
          delay: index * 48,
          easing: EASE,
          fill: "backwards",
        });
        running.add(animation);
        animation.finished.then(() => running.delete(animation), () => running.delete(animation));
      }
    });

    const observe = element => {
      if (seen.has(element) || pending.has(element)) return;
      pending.add(element);
      viewport.observe(element);
    };
    root.querySelectorAll(SELECTOR).forEach(observe);

    const mutations = new MutationObserver(records => {
      for (const { addedNodes } of records) {
        for (const node of addedNodes) {
          if (node.nodeType !== Node.ELEMENT_NODE || !root.contains(node)) continue;
          if (node.matches(SELECTOR)) observe(node);
          node.querySelectorAll(SELECTOR).forEach(observe);
        }
      }
      for (const element of pending) {
        if (root.contains(element)) continue;
        viewport.unobserve(element);
        pending.delete(element);
      }
    });
    mutations.observe(root, { childList: true, subtree: true });

    return () => {
      mutations.disconnect();
      viewport.disconnect();
      running.forEach(animation => animation.cancel());
    };
  }, [ref, reduced]);
}
