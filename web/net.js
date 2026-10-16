// Connection helpers shared by both modes.

export const socketUrl = () =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;

// Versus the computer runs entirely in the browser; this keeps one socket open so the
// server can count the player as online. Returns a function that ends it.
export function announcePlaying() {
  let socket;
  try {
    socket = new WebSocket(socketUrl());
  } catch {
    return () => {};
  }
  socket.addEventListener("open", () => socket.send(JSON.stringify({ type: "playing" })));
  socket.addEventListener("error", () => {}); // being uncounted is fine; the game still works
  return () => socket.close();
}
