// Shared DOM rendering for both game modes. Modes pass plain view data in.

import { countdownLabel, nextTickMs } from "./views.js";

export const GLYPHS = { rock: "✊", paper: "✋", scissors: "✌️" };
export const CONCEALED = "?";
const SECTIONS = ["home", "loading", "setup", "online-setup", "lobby", "play"];
const TOAST_MS = 3500;

export const $ = (id) => document.getElementById(id);

export function show(id) {
  for (const section of SECTIONS) $(section).hidden = section !== id;
}

export function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { el.hidden = true; }, TOAST_MS);
}

export function setVerdict(headline, detail = "", outcome = "") {
  const verdict = $("verdict");
  verdict.className = `verdict ${outcome}`;
  const b = document.createElement("b");
  b.textContent = headline;
  verdict.replaceChildren(b, detail);
}

export function setHand(side, text) {
  const hand = $(`hand-${side}`);
  hand.textContent = text;
  hand.classList.toggle("concealed", text === CONCEALED);
}

export function setBadge(side, text) {
  const badge = $(`badge-${side}`);
  badge.textContent = text;
  badge.hidden = !text;
}

export function setRound(round, rounds) {
  $("round-label").textContent = `Round ${round} / ${rounds}`;
}

export function createMoveButtons(moves, onPick) {
  $("moves").replaceChildren(
    ...moves.map((move) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "move";
      button.dataset.move = move;
      const glyph = document.createElement("span");
      glyph.className = "glyph";
      glyph.textContent = GLYPHS[move] ?? "?";
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = move;
      button.append(glyph, name);
      button.addEventListener("click", () => onPick(move));
      return button;
    }),
  );
}

export function markSelected(move) {
  for (const button of $("moves").querySelectorAll("button")) {
    button.classList.toggle("selected", button.dataset.move === move);
  }
}

export function setMovesEnabled(enabled) {
  for (const button of $("moves").querySelectorAll("button")) button.disabled = !enabled;
}

export function resetBoard({ left, right, rounds }) {
  $("name-left").textContent = left;
  $("name-right").textContent = right;
  setScore({ left: 0, right: 0, draws: 0 });
  setRound(1, rounds);
  setHand("left", GLYPHS.rock);
  setHand("right", GLYPHS.rock);
  setBadge("left", "");
  setBadge("right", "");
  clearOutcome();
  setVerdict("Pick your move.");
  $("history").replaceChildren();
  $("final").hidden = true;
  $("moves").hidden = false;
}

export function setScore({ left, right, draws }) {
  $("score-left").textContent = left;
  $("score-right").textContent = right;
  $("score-draws").textContent = draws;
}

// view: { round, rounds, leftMove, rightMove, outcome, headline, rule, score, rightName }
export function renderReveal(view) {
  $("countdown").hidden = true;
  setHand("left", GLYPHS[view.leftMove]);
  setHand("right", GLYPHS[view.rightMove]);
  setBadge("left", "");
  setBadge("right", "");
  playOutcome(view.outcome);
  setVerdict(view.headline, view.rule ?? "Same hands, no winner.", view.outcome);
  setScore(view.score);
  setRound(view.round, view.rounds);
  addHistory(view);
  document.dispatchEvent(
    new CustomEvent("psr:round", { detail: { outcome: view.outcome, origin: $("arena") } }),
  );
}

const OUTCOMES = ["win", "lose", "draw"];
const CONFETTI_PIECES = 28;
const CONFETTI_COLORS = ["var(--win)", "var(--accent)", "var(--ink)"];
const CONFETTI_MS = 1400;

// Win: winner leaps, loser droops, confetti. Lose: the reverse plus a shake. Draw: hands clash.
function playOutcome(outcome) {
  const arena = $("arena");
  clearOutcome();
  void arena.offsetWidth; // restart the animations
  arena.classList.add(`outcome-${outcome}`);
  if (outcome === "win") burstConfetti(arena);
}

export function clearOutcome() {
  $("arena").classList.remove(...OUTCOMES.map((o) => `outcome-${o}`));
}

function burstConfetti(arena) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const layer = document.createElement("div");
  layer.className = "confetti";
  for (let i = 0; i < CONFETTI_PIECES; i++) {
    const piece = document.createElement("i");
    const angle = Math.random() * Math.PI * 2;
    const distance = 70 + Math.random() * 130;
    piece.style.setProperty("--dx", `${Math.cos(angle) * distance}px`);
    piece.style.setProperty("--dy", `${Math.sin(angle) * distance - 50}px`);
    piece.style.setProperty("--spin", `${Math.random() * 720 - 360}deg`);
    piece.style.background = CONFETTI_COLORS[i % CONFETTI_COLORS.length];
    piece.style.animationDelay = `${Math.random() * 80}ms`;
    layer.append(piece);
  }
  arena.append(layer);
  setTimeout(() => layer.remove(), CONFETTI_MS);
}

function addHistory({ round, leftMove, rightMove, outcome }) {
  const item = document.createElement("li");
  item.className = outcome;
  const n = document.createElement("span");
  n.className = "n";
  n.textContent = `#${round}`;
  const hands = document.createElement("span");
  hands.className = "hands";
  hands.textContent = `${GLYPHS[leftMove]} vs ${GLYPHS[rightMove]}`;
  hands.title = `${leftMove} vs ${rightMove}`;
  const tag = document.createElement("span");
  tag.className = "tag";
  tag.textContent = outcome;
  item.append(n, hands, tag);
  $("history").prepend(item);
}

export function showFinal(summary, { againLabel, onAgain, onLeave }) {
  $("summary").textContent = summary;
  $("again").textContent = againLabel;
  $("again").disabled = false;
  $("again").onclick = onAgain;
  $("leave").onclick = onLeave;
  $("final").hidden = false;
  $("moves").hidden = true;
}

// Big "3, 2, 1, Go!" in the arena. Resolves at zero, or at once if `signal` aborts;
// finalLabel null skips the last word.
// Uses timers, not animation frames, so it keeps time in background tabs.
export function runCountdown(ms, { finalLabel = "Go!", signal } = {}) {
  const el = $("countdown");
  const arena = $("arena");
  el.hidden = false;
  arena.classList.add("pumping");
  const end = performance.now() + ms;
  return new Promise((resolve) => {
    let timer;
    const finish = (label) => {
      clearTimeout(timer);
      arena.classList.remove("pumping");
      if (label) {
        pop(el, label);
        setTimeout(() => { el.hidden = true; }, 450);
      } else {
        el.hidden = true;
      }
      resolve();
    };
    // The round can end early (the server revealed first): stop counting at once.
    signal?.addEventListener("abort", () => finish(null), { once: true });
    const tick = () => {
      if (signal?.aborted) return;
      const left = end - performance.now();
      if (left <= 0) {
        finish(finalLabel);
        return;
      }
      const label = countdownLabel(left);
      if (el.textContent !== label) pop(el, label);
      timer = setTimeout(tick, nextTickMs(left));
    };
    tick();
  });
}

function pop(el, text) {
  el.textContent = text;
  el.classList.remove("pop");
  void el.offsetWidth; // restart the animation
  el.classList.add("pop");
}

export function wireSteppers() {
  for (const button of document.querySelectorAll("[data-step]")) {
    const input = button.closest(".stepper").querySelector("input");
    button.addEventListener("click", () => {
      const current = Number.parseInt(input.value, 10) || 1;
      const next = current + Number(button.dataset.step);
      input.value = String(Math.max(1, Math.min(next, Number(input.max))));
    });
  }
}

export function readRounds(input) {
  const value = Number.parseInt(input.value, 10);
  return Number.isInteger(value) && value >= 1 ? Math.min(value, Number(input.max)) : null;
}
