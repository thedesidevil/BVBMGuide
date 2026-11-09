// Stage-done chime, synthesised with Web Audio (no sound file). Browsers only allow audio after a user gesture;
// the Start/Build/Plan buttons are clicks, and unlockChime() also resumes the context on any first click.
let ctx: AudioContext | null = null;
const KEY = "aigv2.chime.muted";

export function chimeMuted(): boolean {
  try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
}

export function setChimeMuted(muted: boolean): void {
  try { localStorage.setItem(KEY, muted ? "1" : "0"); } catch { /* storage may be blocked */ }
}

function audio(): AudioContext | null {
  try {
    const Ctor = window.AudioContext ?? (window as any).webkitAudioContext;
    if (!Ctor) return null;
    ctx = ctx ?? new Ctor();
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  } catch { return null; }
}

/** Call from a click handler so later chimes are allowed to play. */
export function unlockChime(): void { audio(); }

function note(c: AudioContext, freq: number, start: number, dur: number, gain = 0.18): void {
  const osc = c.createOscillator();
  const g = c.createGain();
  osc.type = "sine";
  osc.frequency.value = freq;
  g.gain.setValueAtTime(0.0001, start);
  g.gain.exponentialRampToValueAtTime(gain, start + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  osc.connect(g).connect(c.destination);
  osc.start(start);
  osc.stop(start + dur + 0.05);
}

/** "done": rising two-note chime (needs your attention). "error": lower, falling pair. */
export function playChime(kind: "done" | "error" = "done"): void {
  if (chimeMuted()) return;
  const c = audio();
  if (!c) return;
  const t = c.currentTime + 0.02;
  if (kind === "error") {
    note(c, 392.0, t, 0.35);        // G4
    note(c, 293.66, t + 0.22, 0.55); // D4
  } else {
    note(c, 659.25, t, 0.4);          // E5
    note(c, 987.77, t + 0.18, 0.7);   // B5
  }
}
