// Versus a friend. The server owns the clock: during each round this client streams
// its current move; at the deadline the server judges and reveals both moves at once.

import { ThrowInput, handCam } from "./hand-cam.js";
import { socketUrl } from "./net.js";
import {
  $, CONCEALED, GLYPHS, clearOutcome, createMoveButtons, renderReveal, resetBoard, setBadge,
  setHand, setRound, setScore, setVerdict, show, showFinal, toast,
} from "./ui.js";
import { onlineRevealView, reconnectDelay, scoreForSeat } from "./views.js";

const MOVES = ["rock", "paper", "scissors"];
const SEAT_KEY = (room) => `psr:seat:${room}`;


function storeSeat(room, token) {
  try { sessionStorage.setItem(SEAT_KEY(room), token); } catch { /* storage unavailable */ }
}

export function storedSeat(room) {
  try { return sessionStorage.getItem(SEAT_KEY(room)); } catch { return null; }
}

function forgetSeat(room) {
  try { sessionStorage.removeItem(SEAT_KEY(room)); } catch { /* storage unavailable */ }
}

export class OnlineGame {
  #ws = null;
  #onExit;
  #room = null;
  #token = null;
  #seat = null;
  #players = [];
  #input = new ThrowInput();
  #roundAbort = null;
  #leaving = false;
  #resuming = false;
  #reconnectAttempt = 0;

  constructor({ onExit }) {
    this.#onExit = onExit;
  }

  start(request) {
    createMoveButtons(MOVES, (move) => this.#input.pick(move));
    $("quit").onclick = () => this.leave();
    $("lobby-leave").onclick = () => this.leave();
    this.#connect(request);
  }

  leave() {
    this.#leaving = true;
    this.#roundAbort?.abort();
    if (this.#token) this.#send({ type: "leave" });
    if (this.#room) forgetSeat(this.#room);
    this.#ws?.close();
    handCam.stop();
    history.replaceState(null, "", location.pathname);
    this.#onExit();
  }

  get #opponent() {
    return this.#players[1 - this.#seat] ?? "Opponent";
  }

  #connect(firstMessage) {
    this.#resuming = firstMessage.type === "resume";
    const ws = new WebSocket(socketUrl());
    this.#ws = ws;
    ws.addEventListener("open", () => this.#send(firstMessage));
    ws.addEventListener("message", (event) => this.#dispatch(JSON.parse(event.data)));
    ws.addEventListener("close", () => this.#onClose(ws));
  }

  #send(message) {
    if (this.#ws?.readyState === WebSocket.OPEN) this.#ws.send(JSON.stringify(message));
  }

  #dispatch(message) {
    switch (message.type) {
      case "joined": return this.#onJoined(message);
      case "lobby": return this.#onLobby(message);
      case "round": return this.#onRound(message);
      case "ready": return this.#onReady(message);
      case "reveal": return this.#onReveal(message);
      case "rematch": return this.#onRematch(message);
      case "sync": return this.#onSync(message);
      case "notice": return toast(message.text);
      case "error": return this.#onError(message);
      default: return undefined;
    }
  }

  #onJoined({ room, seat, token }) {
    const resumed = this.#token !== null;
    this.#resuming = false;
    this.#room = room;
    this.#seat = seat;
    this.#token = token;
    this.#reconnectAttempt = 0;
    storeSeat(room, token);
    history.replaceState(null, "", `?room=${room}`);
    $("lobby-code").textContent = room;
    $("copy-link").onclick = () => this.#copyInvite();
    if (!resumed) show("lobby");
    handCam.open();
  }

  #onLobby({ players }) {
    this.#players = players;
    $("lobby-players").replaceChildren(
      ...players.map((name, i) => {
        const li = document.createElement("li");
        li.textContent = i === this.#seat ? `${name} (you)` : name;
        return li;
      }),
    );
    if (players.length < 2) {
      this.#roundAbort?.abort();
      show("lobby");
    }
  }

  #onRound({ round, rounds, countdown_ms, replay }) {
    if (round === 1 && !replay) {
      resetBoard({ left: "You", right: this.#opponent, rounds });
      show("play");
    }
    this.#throw({ round, rounds, countdownMs: countdown_ms, replay, yourMove: null });
  }

  // One round from this side: show the countdown and stream every move change.
  async #throw({ round, rounds, countdownMs, replay, yourMove }) {
    this.#roundAbort?.abort();
    const abort = new AbortController();
    this.#roundAbort = abort;
    clearOutcome();
    setRound(round, rounds);
    setHand("left", yourMove ? GLYPHS[yourMove] : GLYPHS.rock);
    setHand("right", CONCEALED);
    setBadge("left", yourMove ? "✓" : "");
    setBadge("right", "");
    setVerdict(
      replay ? "Replay!" : "Show your hand",
      `Your move updates live until 0. A photo taken at 0 is shown to ${this.#opponent}.`,
    );

    const move = await this.#input.live({
      countdownMs,
      signal: abort.signal,
      onChange: (next) => {
        this.#send({ type: "move", move: next });
        setVerdict("Your move", `${GLYPHS[next]} ${next}. Change it until 0.`);
      },
    });
    if (abort.signal.aborted) return;
    const image = move ? handCam.snapshot() : null;
    if (image) this.#send({ type: "snapshot", image });
    setVerdict(move ? "Time!" : "No move shown", `Waiting for ${this.#opponent}…`);
  }

  #onReady({ seat }) {
    setBadge(seat === this.#seat ? "left" : "right", "✓");
  }

  #onReveal(message) {
    this.#roundAbort?.abort();
    renderReveal(onlineRevealView(message, this.#seat, this.#opponent));
    if (message.is_over) {
      showFinal(message.summary, {
        againLabel: "Rematch",
        onAgain: () => this.#send({ type: "rematch" }),
        onLeave: () => this.leave(),
      });
    }
  }

  #onRematch({ seat }) {
    if (seat === this.#seat) {
      $("again").disabled = true;
      $("again").textContent = `Waiting for ${this.#opponent}…`;
    } else {
      toast(`${this.#opponent} wants a rematch`);
    }
  }

  // After a reconnect: rebuild the board from the server's snapshot.
  #onSync({ phase, round, rounds, score, remaining_ms, your_move }) {
    resetBoard({ left: "You", right: this.#opponent, rounds });
    setScore(scoreForSeat(score, this.#seat));
    setRound(Math.max(round, 1), rounds);
    show("play");
    if (phase === "throwing" && remaining_ms > 0) {
      this.#throw({ round, rounds, countdownMs: remaining_ms, replay: false, yourMove: your_move });
    } else {
      setVerdict("Reconnected", "The next round starts shortly.");
    }
  }

  #onError({ message }) {
    if (this.#resuming) {
      toast(`Could not rejoin: ${message}`);
      this.leave();
      return;
    }
    if (this.#token === null) {
      $("online-error").textContent = message;
      show("online-setup");
      this.#leaving = true;
      this.#ws?.close();
      return;
    }
    toast(message);
  }

  #onClose(ws) {
    if (ws !== this.#ws || this.#leaving) return;
    this.#roundAbort?.abort();
    const delay = this.#token ? reconnectDelay(this.#reconnectAttempt++) : null;
    if (delay === null) {
      toast("Connection to the server was lost.");
      this.leave();
      return;
    }
    toast("Connection lost. Reconnecting…");
    setTimeout(() => {
      if (!this.#leaving) this.#connect({ type: "resume", room: this.#room, token: this.#token });
    }, delay);
  }

  async #copyInvite() {
    const url = `${location.origin}${location.pathname}?room=${$("lobby-code").textContent}`;
    try {
      await navigator.clipboard.writeText(url);
      toast("Invite link copied");
    } catch {
      toast(url);
    }
  }
}
