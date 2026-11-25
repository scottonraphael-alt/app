export const PREVIEW_DURATION = 270;

function visibleRect(element) {
  const rect = element?.isConnected ? element.getBoundingClientRect() : null;
  return rect?.width && rect.height && rect.bottom > 0 && rect.top < window.innerHeight
    && rect.right > 0 && rect.left < window.innerWidth ? rect : null;
}

function previewCopy(element, kind, rect) {
  const computed = getComputedStyle(element);
  const copy = document.createElement("span");
  copy.className = "iris-preview-flight";
  copy.dataset.kind = kind;
  copy.setAttribute("aria-hidden", "true");
  Object.assign(copy.style, {
    left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`,
    font: computed.font, color: computed.color, borderRadius: computed.borderRadius,
    backgroundColor: computed.backgroundColor,
  });
  const image = kind === "avatar" && element.querySelector("img");
  if (image?.complete && image.naturalWidth) {
    const avatar = document.createElement("img");
    avatar.src = image.currentSrc || image.src;
    avatar.alt = "";
    copy.append(avatar);
  } else {
    copy.textContent = element.textContent.trim() || element.dataset.previewFallback || "";
  }
  return copy;
}

// The copies live above the drawer so its scrolling container cannot clip the transfer.
export function flyPreviewIdentity(source, destination) {
  if (!source || !destination || !Element.prototype.animate) return null;
  const animations = [];
  const cleanup = [];
  for (const kind of ["avatar", "title"]) {
    const from = source.querySelector(`[data-preview-${kind}]`);
    const to = destination.querySelector(`[data-preview-${kind}]`);
    const start = visibleRect(from);
    const end = visibleRect(to);
    if (!start || !end || to.closest("[inert]")) continue;

    const clone = previewCopy(from, kind, start);
    if (!clone.textContent && !clone.childElementCount) continue;
    const scale = kind === "title"
      ? (parseFloat(getComputedStyle(to).fontSize) / parseFloat(getComputedStyle(from).fontSize) || 1)
      : end.width / start.width;
    document.body.append(clone);
    // Hide the destination copy for the duration of the flight without moving its layout.
    const masks = [from, to].map(element => element.animate(
      [{ opacity: 0 }, { opacity: 0 }], { duration: PREVIEW_DURATION },
    ));
    const animation = clone.animate([
      { transform: "translate(0, 0) scale(1)" },
      { transform: `translate(${end.left - start.left}px, ${end.top - start.top}px) scale(${scale})` },
    ], { duration: PREVIEW_DURATION, easing: "cubic-bezier(.22,1,.36,1)" });
    const remove = () => { masks.forEach(mask => mask.cancel()); clone.remove(); };
    animation.finished.then(remove, remove);
    animations.push(animation);
    cleanup.push(remove);
  }
  return animations.length ? () => {
    animations.forEach(animation => animation.cancel());
    cleanup.forEach(remove => remove());
  } : null;
}
