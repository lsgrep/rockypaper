// Entry point: mode selection and setup forms.

import { OnlineGame, storedSeat } from "./online.js";
import { startSolo } from "./solo.js";
import { $, readRounds, show, toast, wireSteppers } from "./ui.js";
import { isRoomCode, onlineLabel } from "./views.js";

const NAME_KEY = "psr:name";
const ONLINE_POLL_MS = 10_000;

function remember(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}

function recall(key) {
  try { return localStorage.getItem(key) ?? ""; } catch { return ""; }
}

function goHome() {
  show("home");
}

async function playSolo(rounds) {
  try {
    await startSolo(rounds, { onExit: goHome, onReplay: () => show("setup") });
  } catch (error) {
    toast(`Could not start Python: ${error.message}`);
    goHome();
  }
}

function wireSoloSetup() {
  const input = $("rounds");
  for (const button of document.querySelectorAll("[data-preset]")) {
    button.addEventListener("click", () => { input.value = button.dataset.preset; });
  }
  $("setup-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const rounds = readRounds(input);
    if (rounds === null) input.reportValidity();
    else playSolo(rounds);
  });
}

function wireOnlineSetup() {
  const nameInput = $("player-name");
  const codeInput = $("room-code");
  const error = $("online-error");
  nameInput.value = recall(NAME_KEY);

  $("online-form").addEventListener("submit", (event) => {
    event.preventDefault();
    error.textContent = "";
    const name = nameInput.value.trim();
    if (!name) {
      nameInput.reportValidity();
      return;
    }
    remember(NAME_KEY, name);
    const joining = event.submitter?.value === "join";
    const code = codeInput.value.trim().toUpperCase();
    if (joining && !isRoomCode(code)) {
      error.textContent = "Room codes are 4 letters or digits.";
      return;
    }
    const request = joining
      ? { type: "join", name, room: code }
      : { type: "create", name, rounds: readRounds($("online-rounds")) ?? 3 };
    new OnlineGame({ onExit: () => show("online-setup") }).start(request);
  });
}

// Header banner: players in online rooms right now. Hidden if the server can't say.
async function refreshOnlineCount() {
  const el = $("online-count");
  try {
    const response = await fetch("/api/online", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const { players } = await response.json();
    el.textContent = onlineLabel(players);
    el.hidden = false;
  } catch {
    el.hidden = true;
  }
}

function watchOnlineCount() {
  refreshOnlineCount();
  setInterval(() => {
    if (!document.hidden) refreshOnlineCount();
  }, ONLINE_POLL_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshOnlineCount();
  });
}

function main() {
  watchOnlineCount();
  wireSteppers();
  wireSoloSetup();
  wireOnlineSetup();
  for (const button of document.querySelectorAll("[data-mode]")) {
    button.addEventListener("click", () => show(button.dataset.mode === "solo" ? "setup" : "online-setup"));
  }
  for (const button of document.querySelectorAll("[data-home]")) button.addEventListener("click", goHome);

  const room = new URLSearchParams(location.search).get("room")?.toUpperCase();
  const token = room ? storedSeat(room) : null;
  if (room && token) {
    new OnlineGame({ onExit: () => show("online-setup") }).start({ type: "resume", room, token });
  } else if (room) {
    $("room-code").value = room;
    show("online-setup");
    $("player-name").focus();
  } else {
    goHome();
  }
}

main();
