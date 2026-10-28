import { useNavigate } from "react-router-dom";

import useDisplayPrefs from "../../hooks/useDisplayPrefs";
import useShortcuts from "../../hooks/useShortcuts";
import FocusIndicator from "./FocusIndicator";
import ShortcutsHelp from "./ShortcutsHelp";

export default function UxLayer() {
  const navigate = useNavigate();
  useDisplayPrefs();
  useShortcuts(navigate);
  return (<><ShortcutsHelp /><FocusIndicator /></>);
}
