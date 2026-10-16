// Pure gesture logic: classification, debouncing, and "held steady" detection.
// No DOM, no MediaPipe, no clock of its own: callers pass `now`, so it is unit-testable.

const MIN_SCORE = 0.5;
const LABEL_TO_MOVE = { Closed_Fist: "rock", Open_Palm: "paper", Victory: "scissors" };

// Landmark indices (tip, middle joint) for index, middle, ring and pinky fingers.
const FINGERS = [[8, 6], [12, 10], [16, 14], [20, 18]];
const EXTENDED_RATIO = 1.1;

const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);

// Fallback when the built-in classifier is unsure: count extended fingers.
export function moveFromLandmarks(landmarks) {
  const wrist = landmarks[0];
  const extended = FINGERS.map(
    ([tip, joint]) => distance(wrist, landmarks[tip]) > distance(wrist, landmarks[joint]) * EXTENDED_RATIO,
  );
  const [index, middle, ring, pinky] = extended;
  const count = extended.filter(Boolean).length;
  if (count === 0) return "rock";
  if (count === 4) return "paper";
  if (index && middle && !ring && !pinky) return "scissors";
  return null;
}

// MediaPipe result -> { move, label, score }; label/score describe what decided the move.
export function readResult(result) {
  const best = result.gestures[0]?.[0];
  if (best && best.score >= MIN_SCORE && LABEL_TO_MOVE[best.categoryName]) {
    return { move: LABEL_TO_MOVE[best.categoryName], label: best.categoryName, score: best.score };
  }
  const landmarks = result.landmarks[0];
  if (!landmarks) return { move: null, label: "no hand", score: 0 };
  const move = moveFromLandmarks(landmarks);
  return { move, label: move ? "finger count" : (best?.categoryName ?? "unknown"), score: best?.score ?? 0 };
}

// Tracks the current reading and since when it has been unchanged.
export class MoveStreak {
  move = null;
  since = 0;

  update(move, now) {
    if (move !== this.move) {
      this.move = move;
      this.since = now;
    }
  }

  // The move if it has been held for `holdMs`, counting only from `startedAt`.
  heldMove(startedAt, now, holdMs) {
    const steadyFor = now - Math.max(this.since, startedAt);
    return this.move && steadyFor >= holdMs ? this.move : null;
  }
}

// Debounces readings: a move "settles" once it has been read for `settleMs`.
// update() returns the newly settled move when it changes, otherwise null.
export class GestureSettler {
  #streak = new MoveStreak();
  #settleMs;
  settled = null;

  constructor(settleMs) {
    this.#settleMs = settleMs;
  }

  update(move, now) {
    this.#streak.update(move, now);
    const steady = now - this.#streak.since >= this.#settleMs;
    if (!steady) return null;
    if (!move) {
      this.settled = null;
      return null;
    }
    if (move === this.settled) return null;
    this.settled = move;
    return move;
  }
}
