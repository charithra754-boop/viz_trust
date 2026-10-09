import { useEffect, useState } from "react";

// Captions for demo videos. Off unless the URL has ?narrate=1 (or &narrate=1), so the normal UI is
// untouched. demo/narrate.py writes the current caption to web/public/narration.json; this polls it.
const ENABLED = new URLSearchParams(window.location.search).get("narrate") === "1";
const POLL_MS = 800;
const TONE_COLOR = {
  info: "var(--text-2)",
  good: "var(--accent)",
  warn: "var(--warning)",
  bad: "var(--danger)",
};

export default function NarrationOverlay() {
  const [caption, setCaption] = useState(null);

  useEffect(() => {
    if (!ENABLED) return undefined;
    let cancelled = false;
    let timer;

    const poll = async () => {
      try {
        const response = await fetch("/narration.json", { cache: "no-store" });
        const body = response.ok ? await response.json() : null;
        if (!cancelled) setCaption((current) => (body?.step === current?.step ? current : body));
      } catch {
        if (!cancelled) setCaption(null); // no narrator running: show nothing
      } finally {
        if (!cancelled) timer = setTimeout(poll, POLL_MS);
      }
    };

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  if (!ENABLED || !caption) return null;

  return (
    <aside
      key={caption.step}
      className="narration"
      style={{ borderLeftColor: TONE_COLOR[caption.tone] ?? TONE_COLOR.info }}
      aria-live="polite"
    >
      <div className="narration-title" style={{ color: TONE_COLOR[caption.tone] ?? TONE_COLOR.info }}>
        {caption.title}
      </div>
      <p className="narration-body">{caption.body}</p>
      <div className="narration-where">where: {caption.where}</div>
    </aside>
  );
}
