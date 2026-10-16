// Homepage lists: open lobbies (with a Join button) and matches being played now.

import { $ } from "./ui.js";
import { liveRoomView, openRoomView } from "./views.js";

function item({ title, detail }, action) {
  const li = document.createElement("li");
  const text = document.createElement("div");
  const strong = document.createElement("b");
  strong.textContent = title;
  const small = document.createElement("small");
  small.textContent = detail;
  text.append(strong, small);
  li.append(text);
  if (action) li.append(action);
  return li;
}

function empty(text) {
  const li = document.createElement("li");
  li.className = "empty";
  li.textContent = text;
  return li;
}

function joinButton(code, onJoin) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "primary ghost small";
  button.textContent = "Join";
  button.addEventListener("click", () => onJoin(code));
  return button;
}

export function renderLobbies({ open, live }, onJoin) {
  $("open-rooms").replaceChildren(
    ...(open.length
      ? open.map((room) => item(openRoomView(room), joinButton(room.code, onJoin)))
      : [empty("No one is waiting. Create a room and it shows up here.")]),
  );
  $("live-rooms").replaceChildren(
    ...(live.length ? live.map((room) => item(liveRoomView(room))) : [empty("No matches right now.")]),
  );
}

export async function fetchLobbies() {
  const response = await fetch("/api/rooms", { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
