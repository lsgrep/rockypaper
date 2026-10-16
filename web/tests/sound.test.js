import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { SOUNDS, isMuted, play, setMuted } from "../sound.js";

describe("sounds", () => {
  it("are short, audible notes", () => {
    for (const [name, notes] of Object.entries(SOUNDS)) {
      assert.ok(notes.length > 0, name);
      for (const n of notes) {
        assert.ok(n.freq >= 40 && n.freq <= 4000, `${name} freq`);
        assert.ok(n.dur > 0 && (n.at ?? 0) + n.dur <= 1, `${name} timing`);
        assert.ok(n.gain > 0 && n.gain <= 0.4, `${name} volume`);
      }
    }
  });

  it("can be muted, and play is harmless without Web Audio", () => {
    setMuted(true);
    assert.equal(isMuted(), true);
    setMuted(false);
    assert.doesNotThrow(() => play("win")); // Node has no AudioContext
  });
});
