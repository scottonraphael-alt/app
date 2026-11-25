import { useEffect, useRef } from 'react';
import { useReducedMotion } from '../motion/Motion';
import './StateMotion.css';

export default function ChangeCue({ value, as: Element = 'span', children, className = '', variant, ...props }) {
  const root = useRef(null), previous = useRef(value);
  const reduced = useReducedMotion();
  useEffect(() => {
    const changed = !Object.is(previous.current, value);
    previous.current = value;
    if (!changed || reduced || !root.current?.animate) return undefined;
    const color = getComputedStyle(root.current).getPropertyValue('--iris-info-soft').trim() || 'transparent';
    const frames = variant === 'assignment' ? [
      { boxShadow: `0 0 0 4px ${color}`, translate: '-6px 0' },
      { boxShadow: '0 0 0 0 transparent', translate: '0 0' },
    ] : [
      { boxShadow: `0 0 0 4px ${color}` },
      { boxShadow: '0 0 0 0 transparent' },
    ];
    const animation = root.current.animate(frames, { duration: 400, easing: 'cubic-bezier(.22,1,.36,1)' });
    return () => animation.cancel();
  }, [value, reduced, variant]);
  return <Element {...props} className={`iris-change-cue ${className}`} ref={root}>{children}</Element>;
}
