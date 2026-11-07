import { useEffect } from "react";
import "../motion/Motion.css";
import { useNavigate } from "react-router-dom";

import useDisplayPrefs from "../../hooks/useDisplayPrefs";
import useShortcuts from "../../hooks/useShortcuts";
import FocusIndicator from "./FocusIndicator";
import ShortcutsHelp from "./ShortcutsHelp";

export default function UxLayer() {
  const navigate = useNavigate();
  useEffect(() => {
    const invalid = event => event.target.setAttribute('data-motion-invalid', 'true');
    const clear = event => event.target.removeAttribute?.('data-motion-invalid');
    document.addEventListener('invalid', invalid, true);
    document.addEventListener('input', clear, true);
    document.addEventListener('change', clear, true);
    return () => {
      document.removeEventListener('invalid', invalid, true);
      document.removeEventListener('input', clear, true);
      document.removeEventListener('change', clear, true);
    };
  }, []);
  useDisplayPrefs();
  useShortcuts(navigate);
  return (<><ShortcutsHelp /><FocusIndicator /></>);
}
