import * as Tooltip from '@radix-ui/react-tooltip';
import './Comfort.css';

// Opt in on icon-only controls. Radix supplies focus, Escape, hover and collision handling.
export default function IconHint({ label, children }) {
  return <Tooltip.Provider delayDuration={350} skipDelayDuration={100}>
    <Tooltip.Root><Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal><Tooltip.Content className="iris-icon-hint" sideOffset={8} collisionPadding={12}>
        {label}<Tooltip.Arrow className="iris-icon-hint-arrow"/>
      </Tooltip.Content></Tooltip.Portal>
    </Tooltip.Root>
  </Tooltip.Provider>;
}
