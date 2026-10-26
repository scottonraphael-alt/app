// Les copies d'avatars sont servies par l'API, y compris quand celle-ci est sur un autre domaine.
export function resolveAvatarUrl(url) {
  if (typeof url !== "string") return "";
  if (url.startsWith("/api/tickets/avatars/")) {
    return `${(process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "")}${url}`;
  }
  return url;
}
