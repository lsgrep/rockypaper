import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  countdownLabel,
  matchesLabel,
  matchResultView,
  liveRoomView,
  openRoomView,
  isRoomCode,
  nextTickMs,
  onlineLabel,
  onlineRevealView,
  outcomeForSeat,
  reconnectDelay,
  scoreForSeat,
  soloRevealView,
} from "../views.js";

const reveal = {
  type: "reveal",
  round: 2,
  rounds: 3,
  moves: ["paper", "rock"],
  snapshots: ["data:alice", null],
  winner: 0,
  rule: "Paper wraps Rock",
  score: { wins: [2, 0], draws: 1 },
  is_over: false,
  summary: null,
};

describe("outcomeForSeat", () => {
  it("is from the viewer's side", () => {
    assert.equal(outcomeForSeat(0, 0), "win");
    assert.equal(outcomeForSeat(0, 1), "lose");
    assert.equal(outcomeForSeat(null, 1), "draw");
  });
});

describe("onlineRevealView", () => {
  it("puts the viewer on the left for seat 0", () => {
    assert.deepEqual(onlineRevealView(reveal, 0, "Bob"), {
      round: 2,
      rounds: 3,
      leftMove: "paper",
      rightMove: "rock",
      outcome: "win",
      headline: "You win the round",
      rule: "Paper wraps Rock",
      score: { left: 2, right: 0, draws: 1 },
      leftPhoto: "data:alice",
      rightPhoto: null,
    });
  });

  it("shows the opponent's photo on the right for seat 1", () => {
    const view = onlineRevealView(reveal, 1, "Alice");
    assert.equal(view.leftPhoto, null);
    assert.equal(view.rightPhoto, "data:alice");
  });

  it("tolerates reveals without snapshots", () => {
    const { snapshots, ...older } = reveal;
    const view = onlineRevealView(older, 0, "Bob");
    assert.equal(view.leftPhoto, null);
    assert.equal(view.rightPhoto, null);
  });

  it("mirrors moves and score for seat 1", () => {
    const view = onlineRevealView(reveal, 1, "Alice");
    assert.equal(view.leftMove, "rock");
    assert.equal(view.rightMove, "paper");
    assert.equal(view.outcome, "lose");
    assert.equal(view.headline, "Alice wins the round");
    assert.deepEqual(view.score, { left: 0, right: 2, draws: 1 });
  });

  it("handles draws", () => {
    const view = onlineRevealView({ ...reveal, winner: null, rule: null }, 1, "Alice");
    assert.equal(view.outcome, "draw");
    assert.equal(view.headline, "Draw");
  });
});

describe("scoreForSeat", () => {
  it("orders wins as you vs opponent", () => {
    assert.deepEqual(scoreForSeat({ wins: [1, 3], draws: 0 }, 1), { left: 3, right: 1, draws: 0 });
  });
});

describe("soloRevealView", () => {
  it("maps the Python session result", () => {
    const view = soloRevealView({
      round: 1,
      rounds: 5,
      human_move: "rock",
      computer_move: "scissors",
      outcome: "win",
      rule: "Rock blunts Scissors",
      score: { human: 1, computer: 0, draws: 0 },
    });
    assert.equal(view.headline, "You win the round");
    assert.equal(view.leftMove, "rock");
    assert.deepEqual(view.score, { left: 1, right: 0, draws: 0 });
    assert.equal(view.leftPhoto, null);
  });

  it("freezes your photo on the left; the computer has none", () => {
    const view = soloRevealView(
      { round: 1, rounds: 1, human_move: "rock", computer_move: "rock", outcome: "draw",
        rule: null, score: { human: 0, computer: 0, draws: 1 } },
      "data:me",
    );
    assert.equal(view.leftPhoto, "data:me");
    assert.equal(view.rightPhoto, null);
  });

  it("names the computer when it wins", () => {
    const view = soloRevealView({
      round: 1, rounds: 1, human_move: "rock", computer_move: "paper", outcome: "lose",
      rule: "Paper wraps Rock", score: { human: 0, computer: 1, draws: 0 },
    });
    assert.equal(view.headline, "Computer wins the round");
  });
});

describe("countdown", () => {
  it("labels whole seconds, rounding up", () => {
    assert.equal(countdownLabel(5000), "5");
    assert.equal(countdownLabel(4001), "5");
    assert.equal(countdownLabel(4000), "4");
    assert.equal(countdownLabel(1), "1");
  });

  it("wakes at the next second boundary", () => {
    assert.equal(nextTickMs(4300), 300);
    assert.equal(nextTickMs(4000), 1000);
    assert.equal(nextTickMs(250), 250);
  });
});

describe("isRoomCode", () => {
  it("accepts four uppercase letters or digits", () => {
    assert.ok(isRoomCode("K7QX"));
    assert.ok(!isRoomCode("k7qx"));
    assert.ok(!isRoomCode("K7Q"));
    assert.ok(!isRoomCode("K7QX1"));
  });
});

describe("reconnectDelay", () => {
  it("backs off then gives up", () => {
    assert.deepEqual([0, 1, 2, 3, 4].map(reconnectDelay), [500, 1000, 2000, 4000, 8000]);
    assert.equal(reconnectDelay(5), null);
  });
});

describe("onlineLabel", () => {
  it("reads naturally for zero, one and many", () => {
    assert.equal(onlineLabel(0), "No one online yet");
    assert.equal(onlineLabel(1), "1 player online");
    assert.equal(onlineLabel(12), "12 players online");
  });
});

describe("room list", () => {
  it("describes an open lobby", () => {
    const room = { code: "K7QX", players: ["Ada"], rounds: 3, round: 0, wins: [0, 0], draws: 0 };
    assert.deepEqual(openRoomView(room), {
      code: "K7QX",
      title: "Ada is waiting",
      detail: "3 rounds · room K7QX",
    });
    assert.equal(openRoomView({ ...room, rounds: 1 }).detail, "1 round · room K7QX");
  });

  it("describes a live match with its score", () => {
    const room = { code: "K7QX", players: ["Ada", "Bo"], rounds: 5, round: 3, wins: [2, 0], draws: 1 };
    assert.deepEqual(liveRoomView(room), {
      code: "K7QX",
      title: "Ada vs Bo",
      detail: "Round 3 of 5 · 2–0 (1 draw)",
    });
    assert.equal(liveRoomView({ ...room, draws: 0 }).detail, "Round 3 of 5 · 2–0");
  });
});

describe("matchResultView", () => {
  it("celebrates a win", () => {
    assert.deepEqual(matchResultView({ left: 2, right: 1, draws: 2 }, "Computer"), {
      outcome: "win",
      headline: "You win the match!",
      score: "2 – 1",
      detail: "You 2 · Computer 1 · 2 draws",
    });
  });

  it("names the opponent when they win", () => {
    const view = matchResultView({ left: 0, right: 3, draws: 0 }, "Bo");
    assert.equal(view.outcome, "lose");
    assert.equal(view.headline, "Bo wins the match");
    assert.equal(view.detail, "You 0 · Bo 3 · no draws");
  });

  it("calls a level score a draw", () => {
    const view = matchResultView({ left: 1, right: 1, draws: 1 }, "Bo");
    assert.equal(view.outcome, "draw");
    assert.equal(view.headline, "Match drawn");
    assert.equal(view.detail, "You 1 · Bo 1 · 1 draw");
  });
});

describe("matchesLabel", () => {
  it("counts with thousands separators", () => {
    assert.equal(matchesLabel(0), "No matches played yet");
    assert.equal(matchesLabel(1), "1 match played");
    assert.equal(matchesLabel(1234), "1,234 matches played");
  });
});
