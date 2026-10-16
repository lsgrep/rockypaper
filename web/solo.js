// Versus the computer: the Python game runs in the browser via Pyodide.

import { ThrowInput, handCam } from "./hand-cam.js";
import {
  $, CONCEALED, GLYPHS, clearOutcome, createMoveButtons, renderReveal, resetBoard, setBadge, setHand, setVerdict,
  show, showFinal,
} from "./ui.js";
import { soloRevealView } from "./views.js";

const PYODIDE_VERSION = "0.26.4";
const PYODIDE_INDEX = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const PACKAGE_DIR = "/home/pyodide";
const COUNTDOWN_MS = 5000;
const RESULT_MS = 2500;
const REPLAY_MS = 1500;

let webModule = null;

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = resolve;
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.append(script);
  });
}

async function loadGame() {
  await loadScript(`${PYODIDE_INDEX}pyodide.js`);
  const pyodide = await globalThis.loadPyodide({ indexURL: PYODIDE_INDEX });
  const manifest = await (await fetch("py/manifest.json")).json();
  const dir = `${PACKAGE_DIR}/${manifest.package}`;
  pyodide.FS.mkdirTree(dir);
  await Promise.all(
    manifest.modules.map(async (name) => {
      const source = await (await fetch(`py/${manifest.package}/${name}`)).text();
      pyodide.FS.writeFile(`${dir}/${name}`, source);
    }),
  );
  pyodide.runPython(`import sys\nif "${PACKAGE_DIR}" not in sys.path: sys.path.insert(0, "${PACKAGE_DIR}")`);
  return pyodide.pyimport("psr.web");
}

const sleep = (ms, signal) =>
  new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
  });

export async function startSolo(rounds, { onExit, onReplay }) {
  if (!webModule) {
    show("loading");
    webModule = await loadGame();
  }
  const session = webModule.WebSession(rounds);
  const input = new ThrowInput();
  const stopped = new AbortController();
  const finish = (next) => () => {
    if (!stopped.signal.aborted) {
      stopped.abort();
      handCam.stop();
      session.destroy();
    }
    next();
  };

  const moves = session.moves;
  createMoveButtons(moves.toJs(), (move) => input.pick(move));
  moves.destroy();
  resetBoard({ left: "You", right: "Computer", rounds });
  $("quit").onclick = finish(onExit);
  show("play");
  handCam.open();
  playRounds(session, input, stopped.signal, { onExit: finish(onExit), onReplay: finish(onReplay) });
}

// Each round: the computer commits (hidden) first, then a countdown during which your
// move follows the camera or your taps. At zero your current move is played.
async function playRounds(session, input, signal, { onExit, onReplay }) {
  while (!signal.aborted) {
    const move = await throwRound(session, input, signal);
    if (signal.aborted) return;
    if (!move) {
      setVerdict("No move in time", "Replaying the round. The computer keeps its move.");
      await sleep(REPLAY_MS, signal);
      continue;
    }

    const proxy = session.play(move);
    const result = proxy.toJs({ dict_converter: Object.fromEntries });
    proxy.destroy();
    renderReveal(soloRevealView(result));
    if (result.is_over) {
      showFinal(result.summary, { againLabel: "Play again", onAgain: onReplay, onLeave: onExit });
      return;
    }
    await sleep(RESULT_MS, signal);
  }
}

function throwRound(session, input, signal) {
  session.start_round().destroy();
  clearOutcome();
  setHand("left", GLYPHS.rock);
  setHand("right", CONCEALED);
  setBadge("right", "🔒");
  const prompt = handCam.ready ? "Show your hand to the camera, or tap." : "Tap your move.";
  setVerdict("Computer has locked in", `${prompt} You can change it until 0.`);
  return input.live({
    countdownMs: COUNTDOWN_MS,
    signal,
    onChange: (move) => setVerdict("Computer has locked in", `Your move: ${GLYPHS[move]} ${move}. Change it until 0.`),
  });
}
