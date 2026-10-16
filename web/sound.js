// Sound effects synthesized with the Web Audio API: no audio files to download.

const MUTE_KEY = "psr:muted";

// Each sound is a few short notes: frequency (Hz), start offset and duration (s).
export const SOUNDS = {
  tick: [{ freq: 880, dur: 0.05, type: "square", gain: 0.05 }],
  lastTick: [{ freq: 1320, dur: 0.08, type: "square", gain: 0.07 }],
  go: [{ freq: 180, slideTo: 55, dur: 0.22, type: "sine", gain: 0.35 }],
  select: [{ freq: 620, dur: 0.04, type: "triangle", gain: 0.07 }],
  win: [523.25, 659.25, 783.99, 1046.5].map((freq, i) => ({
    freq, at: i * 0.08, dur: 0.18, type: "triangle", gain: 0.16,
  })),
  lose: [
    { freq: 392, slideTo: 174, dur: 0.5, type: "sawtooth", gain: 0.06 },
    { freq: 311, slideTo: 138, at: 0.06, dur: 0.5, type: "sawtooth", gain: 0.05 },
  ],
  draw: [
    { freq: 466, dur: 0.11, type: "square", gain: 0.05 },
    { freq: 466, at: 0.16, dur: 0.11, type: "square", gain: 0.05 },
  ],
  "match-win": [523.25, 659.25, 783.99, 1046.5, 783.99, 1046.5].map((freq, i) => ({
    freq, at: i * 0.11, dur: i === 5 ? 0.45 : 0.16, type: "triangle", gain: 0.18,
  })),
  "match-lose": [
    { freq: 294, dur: 0.3, type: "triangle", gain: 0.14 },
    { freq: 247, at: 0.3, dur: 0.3, type: "triangle", gain: 0.14 },
    { freq: 196, at: 0.6, dur: 0.38, type: "triangle", gain: 0.14 },
  ],
  "match-draw": [
    { freq: 392, dur: 0.2, type: "triangle", gain: 0.12 },
    { freq: 392, at: 0.25, dur: 0.3, type: "triangle", gain: 0.12 },
  ],
  join: [
    { freq: 659, dur: 0.12, type: "sine", gain: 0.14 },
    { freq: 988, at: 0.11, dur: 0.2, type: "sine", gain: 0.14 },
  ],
};

let context = null;
let muted = readMuted();

function readMuted() {
  try {
    return localStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}

function audio() {
  const Context = globalThis.AudioContext ?? globalThis.webkitAudioContext;
  if (!Context) return null;
  context ??= new Context();
  if (context.state === "suspended") context.resume();
  return context;
}

function note(ctx, { freq, slideTo, at = 0, dur, type, gain }) {
  const start = ctx.currentTime + at;
  const osc = ctx.createOscillator();
  const env = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, start);
  if (slideTo) osc.frequency.exponentialRampToValueAtTime(slideTo, start + dur);
  env.gain.setValueAtTime(0.0001, start);
  env.gain.exponentialRampToValueAtTime(gain, start + 0.01);
  env.gain.exponentialRampToValueAtTime(0.0001, start + dur);
  osc.connect(env).connect(ctx.destination);
  osc.start(start);
  osc.stop(start + dur + 0.02);
}

export function play(name) {
  if (muted) return;
  const ctx = audio();
  if (!ctx) return;
  for (const n of SOUNDS[name] ?? []) note(ctx, n);
}

export const isMuted = () => muted;

export function setMuted(value) {
  muted = value;
  try {
    localStorage.setItem(MUTE_KEY, value ? "1" : "0");
  } catch {
    /* storage unavailable: the setting just won't stick */
  }
}

// Browsers only allow audio after a user gesture; unlock on the first one.
export function unlockOnFirstGesture() {
  const unlock = () => {
    if (!muted) audio();
  };
  document.addEventListener("pointerdown", unlock, { once: true });
  document.addEventListener("keydown", unlock, { once: true });
}
