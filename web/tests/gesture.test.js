import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { GestureSettler, MoveStreak, moveFromLandmarks, readResult } from "../gesture.js";

// 21 landmarks along the y axis; each finger's tip is far (extended) or near (curled).
function hand(extended) {
  const points = Array.from({ length: 21 }, () => ({ x: 0, y: 0, z: 0 }));
  [[8, 6], [12, 10], [16, 14], [20, 18]].forEach(([tip, joint], i) => {
    points[joint] = { x: 0, y: 1, z: 0 };
    points[tip] = { x: 0, y: extended[i] ? 2 : 0.5, z: 0 };
  });
  return points;
}

const result = ({ label, score = 0.9, landmarks } = {}) => ({
  gestures: label ? [[{ categoryName: label, score }]] : [],
  landmarks: landmarks ? [landmarks] : [],
});

describe("moveFromLandmarks", () => {
  it("reads a fist as rock", () => assert.equal(moveFromLandmarks(hand([0, 0, 0, 0])), "rock"));
  it("reads an open hand as paper", () => assert.equal(moveFromLandmarks(hand([1, 1, 1, 1])), "paper"));
  it("reads index + middle as scissors", () =>
    assert.equal(moveFromLandmarks(hand([1, 1, 0, 0])), "scissors"));
  it("rejects other shapes", () => {
    assert.equal(moveFromLandmarks(hand([1, 0, 0, 0])), null);
    assert.equal(moveFromLandmarks(hand([1, 1, 1, 0])), null);
  });
});

describe("readResult", () => {
  it("maps confident classifier labels to moves", () => {
    assert.deepEqual(readResult(result({ label: "Victory", score: 0.93 })), {
      move: "scissors",
      label: "Victory",
      score: 0.93,
    });
    assert.equal(readResult(result({ label: "Closed_Fist" })).move, "rock");
    assert.equal(readResult(result({ label: "Open_Palm" })).move, "paper");
  });

  it("falls back to finger counting when the classifier is unsure", () => {
    const reading = readResult(result({ label: "Victory", score: 0.3, landmarks: hand([0, 0, 0, 0]) }));
    assert.deepEqual(reading, { move: "rock", label: "finger count", score: 0.3 });
  });

  it("falls back for labels that are not moves", () => {
    const reading = readResult(result({ label: "Thumb_Up", landmarks: hand([1, 1, 1, 1]) }));
    assert.equal(reading.move, "paper");
  });

  it("reports no hand", () => {
    assert.deepEqual(readResult(result()), { move: null, label: "no hand", score: 0 });
  });

  it("reports an unrecognised shape without a move", () => {
    const reading = readResult(result({ label: "Pointing_Up", landmarks: hand([1, 0, 0, 0]) }));
    assert.deepEqual(reading, { move: null, label: "Pointing_Up", score: 0.9 });
  });
});

describe("MoveStreak", () => {
  it("holds once the same move lasts long enough after the start", () => {
    const streak = new MoveStreak();
    streak.update("rock", 0);
    streak.update("rock", 300);
    assert.equal(streak.heldMove(100, 450, 400), null); // only 350 ms since start
    assert.equal(streak.heldMove(100, 500, 400), "rock");
  });

  it("restarts the streak when the move changes", () => {
    const streak = new MoveStreak();
    streak.update("rock", 0);
    streak.update("paper", 500);
    assert.equal(streak.heldMove(0, 800, 400), null);
    assert.equal(streak.heldMove(0, 900, 400), "paper");
  });

  it("never holds 'no hand'", () => {
    const streak = new MoveStreak();
    streak.update(null, 0);
    assert.equal(streak.heldMove(0, 10_000, 400), null);
  });
});

describe("GestureSettler", () => {
  it("emits a move once it settles, and only once", () => {
    const settler = new GestureSettler(150);
    assert.equal(settler.update("rock", 0), null);
    assert.equal(settler.update("rock", 100), null);
    assert.equal(settler.update("rock", 150), "rock");
    assert.equal(settler.update("rock", 400), null);
    assert.equal(settler.settled, "rock");
  });

  it("ignores flickers shorter than the settle time", () => {
    const settler = new GestureSettler(150);
    settler.update("rock", 0);
    settler.update("rock", 200);
    assert.equal(settler.update("paper", 210), null);
    assert.equal(settler.update("rock", 260), null); // back before paper settled
    assert.equal(settler.settled, "rock");
  });

  it("emits the new move after a real change", () => {
    const settler = new GestureSettler(150);
    settler.update("rock", 0);
    settler.update("rock", 200);
    settler.update("scissors", 300);
    assert.equal(settler.update("scissors", 460), "scissors");
  });

  it("clears once the hand has been gone long enough", () => {
    const settler = new GestureSettler(150);
    settler.update("paper", 0);
    settler.update("paper", 200);
    settler.update(null, 300);
    settler.update(null, 460);
    assert.equal(settler.settled, null);
    assert.equal(settler.update("paper", 470), null);
    assert.equal(settler.update("paper", 620), "paper"); // re-emitted after the gap
  });
});
