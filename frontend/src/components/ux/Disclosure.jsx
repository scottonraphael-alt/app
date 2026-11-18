import { useState } from 'react';
import * as Collapsible from '@radix-ui/react-collapsible';
import { ChevronDown } from 'lucide-react';
import './StateMotion.css';

export default function Disclosure({ title, open, defaultOpen = false, onOpenChange, children, className = '', ...props }) {
  const [localOpen, setLocalOpen] = useState(defaultOpen);
  const expanded = open ?? localOpen;
  const change = next => { setLocalOpen(next); onOpenChange?.(next); };
  return <Collapsible.Root {...props} open={expanded} onOpenChange={change} className={`iris-disclosure ${className}`}>
    <Collapsible.Trigger className="iris-disclosure-trigger"><ChevronDown size={16} aria-hidden="true"/><span>{title}</span></Collapsible.Trigger>
    <Collapsible.Content className="iris-disclosure-content" aria-hidden={!expanded} inert={!expanded ? true : undefined}>
      <div className="iris-disclosure-inner">{children}</div>
    </Collapsible.Content>
  </Collapsible.Root>;
}
