import { useState } from "react";
import { resolveAvatarUrl } from "../../utils/avatar";

export default function PreviewAvatar({ person, label, url, className = "" }) {
  const [failed, setFailed] = useState(null);
  const avatar = url ?? resolveAvatarUrl(person?.avatar_url);
  const initial = label?.trim().slice(0, 1).toUpperCase() || "·";
  return <span className={`iris-preview-avatar ${className}`} data-preview-avatar="" data-preview-fallback={initial} aria-hidden="true">
    {avatar && avatar !== failed ? <img src={avatar} alt="" onError={() => setFailed(avatar)} /> : initial}
  </span>;
}
