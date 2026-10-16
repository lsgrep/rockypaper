// Entry point: mode selection and setup forms.

import { fetchLobbies, renderLobbies } from "./lobbies.js";
import { OnlineGame, storedSeat } from "./online.js";
import { isMuted, play, setMuted, unlockOnFirstGesture } from "./sound.js";
import { startSolo } from "./solo.js";
import { $, readRounds, show, toast, wireSteppers } from "./ui.js";
import { isRoomCode, matchesLabel, onlineLabel } from "./views.js";

const NAME_KEY = "psr:name";
const ONLINE_POLL_MS = 10_000;
const PRESENCE_SETTLE_MS = 1_000;
const LOBBY_POLL_MS = 4_000;

function remember(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}

function recall(key) {
  try { return localStorage.getItem(key) ?? ""; } catch { return ""; }
}

function goHome() {
  show("home");
  refreshLobbies();
}

function startOnline(request) {
  new OnlineGame({ onExit: () => show("online-setup") }).start(request);
  setTimeout(refreshOnlineCount, PRESENCE_SETTLE_MS);
}

// From the homepage list: join straight away if we know the player's name.
function joinListedRoom(code) {
  const name = recall(NAME_KEY);
  if (name) {
    startOnline({ type: "join", name, room: code });
    return;
  }
  $("room-code").value = code;
  show("online-setup");
  $("player-name").focus();
}

async function refreshLobbies() {
  if ($("home").hidden) return;
  try {
    renderLobbies(await fetchLobbies(), joinListedRoom);
  } catch {
    renderLobbies({ open: [], live: [] }, joinListedRoom);
  }
}

async function playSolo(rounds) {
  try {
    await startSolo(rounds, { onExit: goHome, onReplay: () => show("setup") });
    setTimeout(refreshOnlineCount, PRESENCE_SETTLE_MS); // include ourselves right away
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
      : {
          type: "create",
          name,
          rounds: readRounds($("online-rounds")) ?? 3,
          public: $("room-public").checked,
        };
    startOnline(request);
  });
}

// Header banner: players online now and matches played so far. Hidden if unavailable.
async function refreshOnlineCount() {
  const online = $("online-count");
  const played = $("matches-count");
  try {
    const response = await fetch("/api/stats", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const { players, matches } = await response.json();
    online.textContent = onlineLabel(players);
    played.textContent = matchesLabel(matches.online + matches.computer);
    played.title = `${matches.online} online · ${matches.computer} vs the computer`;
    online.hidden = played.hidden = false;
  } catch {
    online.hidden = played.hidden = true;
  }
}

function watchOnlineCount() {
  refreshOnlineCount();
  setInterval(() => {
    if (!document.hidden) refreshOnlineCount();
  }, ONLINE_POLL_MS);
  setInterval(() => {
    if (!document.hidden) refreshLobbies();
  }, LOBBY_POLL_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    refreshOnlineCount();
    refreshLobbies();
  });
}

function wireSoundToggle() {
  const button = $("sound-toggle");
  const render = () => {
    const on = !isMuted();
    button.textContent = on ? "🔊" : "🔇";
    button.setAttribute("aria-pressed", String(on));
    button.title = button.ariaLabel = on ? "Sound on" : "Sound off";
  };
  button.addEventListener("click", () => {
    setMuted(!isMuted());
    render();
    play("select");
  });
  render();
  unlockOnFirstGesture();
}

// The title goes home from anywhere; mid-game it leaves properly first.
function wireHomeLink() {
  $("home-link").addEventListener("click", (event) => {
    event.preventDefault();
    if (!$("play").hidden) $("quit").click();
    else if (!$("lobby").hidden) $("lobby-leave").click();
    goHome();
  });
}

function main() {
  wireSoundToggle();
  wireHomeLink();
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
