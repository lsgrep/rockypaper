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
  };
}

const SOLO_HEADLINES = { win: "You win the round", lose: "Computer wins the round", draw: "Draw" };

// psr.web.WebSession.play() result -> board view.
export function soloRevealView(result) {
  return {
    round: result.round,
    rounds: result.rounds,
    leftMove: result.human_move,
    rightMove: result.computer_move,
    outcome: result.outcome,
    headline: SOLO_HEADLINES[result.outcome],
    rule: result.rule,
    score: { left: result.score.human, right: result.score.computer, draws: result.score.draws },
  };
}

// Countdown display: whole seconds remaining, rounded up ("5" ... "1").
export const countdownLabel = (msLeft) => String(Math.ceil(msLeft / 1000));

// Wait until the label next changes (the next whole-second boundary).
export const nextTickMs = (msLeft) => Math.min(msLeft, msLeft % 1000 || 1000);
