// The player's camera, live gesture readout, and the countdown → throw sequence
// shared by both game modes.

import { GestureCamera } from "./camera.js";
import { GestureSettler } from "./gesture.js";
import {
  $, GLYPHS, markSelected, runCountdown, setHand, setMovesEnabled, setVerdict,
} from "./ui.js";

const HOLD_MS = 400; // the same gesture must be read this long after "Shoot!" to count
const SETTLE_MS = 150; // live updates ignore gestures that flicker for less than this

class HandCam {
  #camera = null;
  #opening = null;
  #generation = 0;
  #watchers = new Set();
  #settler = new GestureSettler(SETTLE_MS);
  mirror = false; // while true, live readings are shown as the player's hand

  get ready() {
    return this.#camera !== null;
  }

  open() {
    this.#opening ??= this.#open(this.#generation);
    return this.#opening;
  }

  stop() {
    this.#generation += 1;
    this.#camera?.stop();
    this.#camera = null;
    this.#opening = null;
    $("arena").classList.remove("live");
    $("camera-status").hidden = true;
  }

  // Calls fn(move) with the current settled gesture now (if any) and whenever it changes.
  watch(fn) {
    this.#watchers.add(fn);
    if (this.#settler.settled) fn(this.#settler.settled);
    return () => this.#watchers.delete(fn);
  }

  readThrow({ timeoutMs, signal }) {
    if (!this.#camera) return Promise.resolve(null);
    return this.#camera.waitForStableMove({ holdMs: HOLD_MS, timeoutMs, signal });
  }

  async #open(generation) {
    const status = $("camera-status");
    status.hidden = false;
    if (!navigator.mediaDevices?.getUserMedia) {
      status.textContent = "No camera access here (needs https or localhost). Use the buttons.";
      return false;
    }
    status.textContent = "Loading hand model…";
    try {
      const camera = await GestureCamera.open({
        video: $("camera"),
        overlay: $("camera-overlay"),
        onReading: (reading) => this.#onReading(reading),
      });
      if (generation !== this.#generation) {
        camera.stop();
        return false;
      }
      this.#camera = camera;
      $("arena").classList.add("live");
      status.textContent = "Camera on: show your hand";
      return true;
    } catch (error) {
      status.textContent = `Camera unavailable (${error.message}). Use the buttons.`;
      console.warn("Camera disabled:", error);
      return false;
    }
  }

  #onReading({ move, label, score }) {
    const confidence = score ? ` ${Math.round(score * 100)}%` : "";
    $("camera-status").textContent = move
      ? `Detected ${GLYPHS[move]} ${move} (${label}${confidence})`
      : `Detected: ${label}`;
    if (this.mirror && move) setHand("left", GLYPHS[move]);
    this.#settle(move);
  }

  #settle(move) {
    const settled = this.#settler.update(move, performance.now());
    if (settled) for (const fn of this.#watchers) fn(settled);
  }
}

export const handCam = new HandCam();

// Button taps feed into the same throw as the camera.
export class ThrowInput {
  #tap = null;

  pick(move) {
    this.#tap?.(move);
  }

  // Counts down while the move follows the camera (or the latest tap); the move
  // showing at zero is the one played. Resolves null if nothing was shown or on abort.
  async live({ countdownMs, signal, onChange }) {
    let current = null;
    const choose = (move) => {
      current = move;
      setHand("left", GLYPHS[move]);
      markSelected(move);
      onChange(move);
    };
    this.#tap = choose;
    const unwatch = handCam.watch(choose);
    setMovesEnabled(true);
    try {
      await runCountdown(countdownMs, { finalLabel: null, signal });
    } finally {
      unwatch();
      this.#tap = null;
      setMovesEnabled(false);
      markSelected(null);
    }
    return signal.aborted ? null : current;
  }

  // "3, 2, 1, Shoot!", then the first of: a steady camera gesture or a button tap.
  // Resolves with the move, or null if `signal` aborts.
  async next({ countdownMs, cameraMs, signal }) {
    setMovesEnabled(false);
    handCam.mirror = true;
    try {
      await runCountdown(countdownMs, { signal });
      if (signal.aborted) return null;
      setMovesEnabled(true);
      setVerdict("Shoot!", handCam.ready ? "Hold your hand still…" : "Tap your move.");

      const done = new AbortController();
      const stop = () => done.abort();
      signal.addEventListener("abort", stop, { once: true });
      const tapped = new Promise((resolve) => { this.#tap = resolve; });
      const aborted = new Promise((resolve) => done.signal.addEventListener("abort", () => resolve(null)));
      const seen = handCam.readThrow({ timeoutMs: cameraMs, signal: done.signal }).then((move) => {
        if (move) return move;
        if (!done.signal.aborted && handCam.ready) setVerdict("Couldn't read your hand", "Tap your move instead.");
        return new Promise(() => {}); // fall back to a tap
      });
      const move = await Promise.race([tapped, seen, aborted]);
      done.abort();
      signal.removeEventListener("abort", stop);
      return move;
    } finally {
      this.#tap = null;
      handCam.mirror = false;
      setMovesEnabled(false);
    }
  }
}
