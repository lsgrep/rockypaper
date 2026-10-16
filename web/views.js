// Pure mappings from game data (server messages, Python results) to what the UI shows.

export const ROOM_CODE = /^[A-Z0-9]{4}$/;
export const RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000, 8000];

export const isRoomCode = (code) => ROOM_CODE.test(code);

// Backoff for the nth reconnect attempt (0-based), or null once we should give up.
export const reconnectDelay = (attempt) => RECONNECT_DELAYS_MS[attempt] ?? null;

export function outcomeForSeat(winner, seat) {
  if (winner === null) return "draw";
  return winner === seat ? "win" : "lose";
}

// Server scores are per seat; the board shows "you" on the left.
export function scoreForSeat(score, seat) {
  return { left: score.wins[seat], right: score.wins[1 - seat], draws: score.draws };
}

export function onlineRevealView(message, seat, opponent) {
  const outcome = outcomeForSeat(message.winner, seat);
  const headlines = { win: "You win the round", lose: `${opponent} wins the round`, draw: "Draw" };
  return {
    round: message.round,
    rounds: message.rounds,
    leftMove: message.moves[seat],
    rightMove: message.moves[1 - seat],
    outcome,
    headline: headlines[outcome],
    rule: message.rule,
    score: scoreForSeat(message.score, seat),
    leftPhoto: message.snapshots?.[seat] ?? null,
    rightPhoto: message.snapshots?.[1 - seat] ?? null,
  };
}

const SOLO_HEADLINES = { win: "You win the round", lose: "Computer wins the round", draw: "Draw" };

// psr.web.WebSession.play() result -> board view; `photo` is your frame at zero, if any.
export function soloRevealView(result, photo = null) {
  return {
    round: result.round,
    rounds: result.rounds,
    leftMove: result.human_move,
    rightMove: result.computer_move,
    outcome: result.outcome,
    headline: SOLO_HEADLINES[result.outcome],
    rule: result.rule,
    score: { left: result.score.human, right: result.score.computer, draws: result.score.draws },
    leftPhoto: photo,
    rightPhoto: null,
  };
}

// Countdown display: whole seconds remaining, rounded up ("5" ... "1").
export const countdownLabel = (msLeft) => String(Math.ceil(msLeft / 1000));

// Wait until the label next changes (the next whole-second boundary).
export const nextTickMs = (msLeft) => Math.min(msLeft, msLeft % 1000 || 1000);

// Header banner text for the number of players connected to online rooms.
export function onlineLabel(players) {
  if (players === 0) return "No one online yet";
  return players === 1 ? "1 player online" : `${players} players online`;
}

// Homepage room list entries (from GET /api/rooms).
export function openRoomView(room) {
  return {
    code: room.code,
    title: `${room.players[0]} is waiting`,
    detail: `${room.rounds} ${room.rounds === 1 ? "round" : "rounds"} · room ${room.code}`,
  };
}

export function liveRoomView(room) {
  const [first, second] = room.players;
  const draws = room.draws ? ` (${room.draws} ${room.draws === 1 ? "draw" : "draws"})` : "";
  return {
    code: room.code,
    title: `${first} vs ${second}`,
    detail: `Round ${Math.max(room.round, 1)} of ${room.rounds} · ${room.wins[0]}–${room.wins[1]}${draws}`,
  };
}

// End-of-match card, from the board's score ({ left: you, right: them, draws }).
export function matchResultView(score, opponent) {
  const outcome = score.left === score.right ? "draw" : score.left > score.right ? "win" : "lose";
  const headlines = {
    win: "You win the match!",
    lose: `${opponent} wins the match`,
    draw: "Match drawn",
  };
  const draws = score.draws ? `${score.draws} ${score.draws === 1 ? "draw" : "draws"}` : "no draws";
  return {
    outcome,
    headline: headlines[outcome],
    score: `${score.left} – ${score.right}`,
    detail: `You ${score.left} · ${opponent} ${score.right} · ${draws}`,
  };
}

// Header banner text for the lifetime number of matches played.
export function matchesLabel(total) {
  if (total === 0) return "No matches played yet";
  const count = total.toLocaleString("en-US");
  return total === 1 ? "1 match played" : `${count} matches played`;
}
