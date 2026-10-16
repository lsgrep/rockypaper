// Connection helpers shared by both modes.

export const socketUrl = () =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;

// Versus the computer runs entirely in the browser; this keeps one socket open so the
// server can count the player as online, and report the match when it ends.
export function announcePlaying() {
  let socket;
  try {
    socket = new WebSocket(socketUrl());
  } catch {
    return { finished() {}, end() {} };
  }
  const send = (message) => {
    if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
  };
  socket.addEventListener("open", () => send({ type: "playing" }));
  socket.addEventListener("error", () => {}); // being uncounted is fine; the game still works
  return {
    finished: () => send({ type: "finished" }),
    end: () => socket.close(),
  };
}
