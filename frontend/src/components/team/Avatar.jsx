/** Pastille d'avatar avec repli sur l'initiale. */
export default function Avatar({ name, url, size = 44 }) {
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  return url ? (
    <img className="tm-avatar" src={url} alt="" width={size} height={size} loading="lazy" />
  ) : (
    <span className="tm-avatar tm-avatar--fallback" style={{ width: size, height: size }} aria-hidden="true">{initial}</span>
  );
}
