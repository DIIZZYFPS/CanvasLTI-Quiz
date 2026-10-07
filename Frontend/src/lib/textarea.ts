// Properties that affect where text wraps; copied onto a hidden mirror element.
const MIRRORED_PROPERTIES = [
  "box-sizing", "width", "font-family", "font-size", "font-weight", "font-style",
  "letter-spacing", "line-height", "text-transform", "word-spacing", "text-indent", "tab-size",
  "padding-top", "padding-right", "padding-bottom", "padding-left",
  "border-top-width", "border-right-width", "border-bottom-width", "border-left-width",
];

/** Pixels from the top of the textarea's content to the line containing `offset`. */
function measureOffsetTop(textarea: HTMLTextAreaElement, offset: number): number {
  const style = getComputedStyle(textarea);
  const mirror = document.createElement("div");
  for (const property of MIRRORED_PROPERTIES) {
    mirror.style.setProperty(property, style.getPropertyValue(property));
  }
  mirror.style.position = "absolute";
  mirror.style.visibility = "hidden";
  mirror.style.left = "-9999px";
  mirror.style.top = "0";
  mirror.style.height = "auto";
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.overflowWrap = "break-word";
  mirror.textContent = textarea.value.slice(0, offset);

  const marker = document.createElement("span");
  marker.textContent = "\u200b";
  mirror.appendChild(marker);

  document.body.appendChild(mirror);
  const top = marker.offsetTop;
  document.body.removeChild(mirror);
  return top;
}

/**
 * Bring the character at `offset` into view, whichever thing scrolls.
 *
 * Counting newlines isn't enough because long lines wrap, so the text before `offset` is laid
 * out in an off-screen element styled like the textarea and the height it reaches is where the
 * offset sits. The textarea in this app grows with its content (it never scrolls internally),
 * so the *page* has to scroll; a fixed-height textarea scrolls itself. This does both, so it
 * works in either case.
 */
export function revealTextareaOffset(textarea: HTMLTextAreaElement, offset: number): void {
  const top = measureOffsetTop(textarea, offset);

  // A fixed-height textarea scrolls internally (a no-op when it auto-grows).
  textarea.scrollTop = Math.max(0, top - textarea.clientHeight / 3);

  // Then place that line about a third of the way down the window, clear of the sticky header.
  const rect = textarea.getBoundingClientRect();
  const lineInViewport = rect.top + top - textarea.scrollTop;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollBy({ top: lineInViewport - window.innerHeight / 3, behavior: reduceMotion ? "auto" : "smooth" });
}
