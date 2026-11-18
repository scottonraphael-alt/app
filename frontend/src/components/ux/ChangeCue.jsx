import { useEffect, useRef } from 'react';
import { useReducedMotion } from '../motion/Motion';
import './StateMotion.css';

export default function ChangeCue({ value, as: Element = 'span', children, className = '', ...props }) {
  const root = useRef(null), previous = useRef(value);
  const reduced = useReducedMotion();
  useEffect(() => {
    const changed = !Object.is(previous.current, value);
    previous.current = value;
    if (!changed || reduced || !root.current?.animate) return undefined;
    const color = getComputedStyle(root.current).getPropertyValue('--iris-info-soft').trim() || 'transparent';
    const animation = root.current.animate([
      { boxShadow: `0 0 0 4px ${color}` },
      { boxShadow: '0 0 0 0 transparent' },
    ], { duration: 400, easing: 'ease-out' });
    return () => animation.cancel();
  }, [value, reduced]);
  return <Element {...props} className={`iris-change-cue ${className}`} ref={root}>{children}</Element>;
}
