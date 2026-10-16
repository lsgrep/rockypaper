// Hand-gesture reading from the webcam with MediaPipe's Gesture Recognizer (WASM + WebGL).
// The runtime and model are served from this site (scripts/fetch_models.py).
// Frames never leave the browser; only the resulting move is used.

import { MoveStreak, readResult } from "./gesture.js";

const VENDOR = new URL("./vendor/mediapipe/", import.meta.url).href;
const MODEL_URL = `${VENDOR}gesture_recognizer.task`;
const HAND_COLOR = "#ff6a4d";
async function loadVision() {
  const vision = await import(`${VENDOR}vision_bundle.mjs`);
  const fileset = await vision.FilesetResolver.forVisionTasks(`${VENDOR}wasm`);
  return { vision, recognizer: await createRecognizer(vision.GestureRecognizer, fileset) };
}

async function createRecognizer(GestureRecognizer, fileset) {
  const options = (delegate) => ({
    baseOptions: { modelAssetPath: MODEL_URL, delegate },
    runningMode: "VIDEO",
    numHands: 1,
  });
  try {
    return await GestureRecognizer.createFromOptions(fileset, options("GPU"));
  } catch {
    return GestureRecognizer.createFromOptions(fileset, options("CPU"));
  }
}

export class GestureCamera {
  #video;
  #overlay;
  #stream;
  #recognizer;
  #drawing;
  #connections;
  #onReading;
  #streak = new MoveStreak();
  #lastFrameTime = -1;
  #running = true;
  #waiters = new Set();

  constructor({ video, overlay, stream, vision, recognizer, onReading }) {
    this.#video = video;
    this.#overlay = overlay;
    this.#stream = stream;
    this.#recognizer = recognizer;
    this.#drawing = new vision.DrawingUtils(overlay.getContext("2d"));
    this.#connections = vision.GestureRecognizer.HAND_CONNECTIONS;
    this.#onReading = onReading;
    requestAnimationFrame(() => this.#frame());
  }

  // onReading({ move, label, score }) is called for every processed frame.
  static async open({ video, overlay, onReading = () => {} }) {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    video.srcObject = stream;
    await video.play();
    try {
      const { vision, recognizer } = await loadVision();
      return new GestureCamera({ video, overlay, stream, vision, recognizer, onReading });
    } catch (error) {
      for (const track of stream.getTracks()) track.stop();
      throw error;
    }
  }

  // Resolves with a move once the same one has been read for `holdMs` after this call,
  // or null after `timeoutMs` (timer-based, so it fires even when frames stop) or when aborted.
  waitForStableMove({ holdMs, timeoutMs, signal }) {
    return new Promise((resolve) => {
      const startedAt = performance.now();
      const waiter = (now) => {
        const move = this.#streak.heldMove(startedAt, now, holdMs);
        if (move) finish(move);
      };
      const timer = setTimeout(() => finish(null), timeoutMs);
      const finish = (move) => {
        clearTimeout(timer);
        this.#waiters.delete(waiter);
        resolve(move);
      };
      signal?.addEventListener("abort", () => finish(null), { once: true });
      this.#waiters.add(waiter);
    });
  }

  stop() {
    this.#running = false;
    for (const track of this.#stream.getTracks()) track.stop();
    this.#video.srcObject = null;
    this.#overlay.getContext("2d").clearRect(0, 0, this.#overlay.width, this.#overlay.height);
    this.#recognizer.close();
  }

  #frame() {
    if (!this.#running) return;
    const now = performance.now();
    if (this.#video.readyState >= 2 && this.#video.currentTime !== this.#lastFrameTime) {
      this.#lastFrameTime = this.#video.currentTime;
      const result = this.#recognizer.recognizeForVideo(this.#video, now);
      this.#draw(result);
      const reading = readResult(result);
      this.#streak.update(reading.move, now);
      this.#onReading(reading);
    }
    for (const waiter of [...this.#waiters]) waiter(now);
    requestAnimationFrame(() => this.#frame());
  }

  #draw(result) {
    const canvas = this.#overlay;
    if (canvas.width !== this.#video.videoWidth) {
      canvas.width = this.#video.videoWidth;
      canvas.height = this.#video.videoHeight;
    }
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    for (const landmarks of result.landmarks) {
      this.#drawing.drawConnectors(landmarks, this.#connections, { color: HAND_COLOR, lineWidth: 4 });
      this.#drawing.drawLandmarks(landmarks, { color: "#ffffff", fillColor: HAND_COLOR, radius: 4, lineWidth: 1 });
    }
  }
}
