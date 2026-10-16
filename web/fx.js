"use strict";

// Background shader: drifting topographic contours, plus a ripple after each round.
// Listens for the "psr:round" event from app.js; does nothing without WebGL.

const VERTEX_SHADER = `
attribute vec2 aPosition;
void main() { gl_Position = vec4(aPosition, 0.0, 1.0); }
`;

const FRAGMENT_SHADER = `
precision mediump float;
uniform vec2 uResolution;
uniform float uTime;
uniform vec3 uBg;
uniform vec3 uInk;
uniform vec3 uAccent;
uniform vec3 uPulseColor;
uniform vec2 uPulseOrigin;
uniform float uPulseAge;
uniform float uPulseKind; // 0 win: sparkling burst out, 1 lose: ring implodes + dim, 2 draw: soft double ripple

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
             mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}

float fbm(vec2 p) {
  float value = 0.0;
  float amplitude = 0.5;
  for (int i = 0; i < 5; i++) {
    value += amplitude * noise(p);
    p = mat2(1.6, 1.2, -1.2, 1.6) * p;
    amplitude *= 0.5;
  }
  return value;
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.y;
  float t = uTime * 0.035;

  float d = distance(gl_FragCoord.xy, uPulseOrigin) / uResolution.y;
  float isWin = 1.0 - step(0.5, uPulseKind);
  float isLose = step(0.5, uPulseKind) * (1.0 - step(1.5, uPulseKind));
  float isDraw = step(1.5, uPulseKind);
  float fade = exp(-uPulseAge * mix(1.4, 0.7, isLose));
  float radius = isWin * uPulseAge * 1.1 + isLose * max(1.2 - uPulseAge * 0.9, 0.0) + isDraw * uPulseAge * 0.45;
  float width = mix(12.0, 6.0, isDraw);
  float ring = exp(-pow((d - radius) * width, 2.0)) * fade;
  ring += isDraw * exp(-pow((d - uPulseAge * 0.22) * 6.0, 2.0)) * fade;
  float glow = exp(-d * 3.5) * exp(-uPulseAge * 2.2) * (1.0 - isLose);
  float sparkle = isWin * ring * step(0.97, hash(floor(gl_FragCoord.xy / 4.0) + floor(uTime * 24.0)));

  vec2 warp = vec2(fbm(uv * 1.5 + t), fbm(uv * 1.5 - t + 3.7));
  float height = fbm(uv * 2.0 + warp * 1.7 + t * 0.4) + ring * 0.12;

  float band = abs(fract(height * 10.0) - 0.5);
  float contour = 1.0 - smoothstep(0.0, 0.06, band);

  vec3 color = uBg;
  color = mix(color, uAccent, smoothstep(0.55, 0.85, height) * 0.14);
  color = mix(color, uInk, contour * 0.09);
  color = mix(color, uPulseColor, clamp(ring * 0.55 + glow * 0.3 + contour * ring * 0.6, 0.0, 1.0));
  color *= 1.0 - isLose * 0.35 * exp(-uPulseAge * 1.2) * smoothstep(0.2, 1.2, d);
  color = mix(color, vec3(1.0), clamp(sparkle, 0.0, 1.0));
  gl_FragColor = vec4(color, 1.0);
}
`;

const MAX_PIXEL_RATIO = 1.5;
const PULSE_KINDS = { win: 0, lose: 1, draw: 2 };
const IDLE_PULSE_AGE = 1e3;

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader) ?? "shader compile failed");
  }
  return shader;
}

function createProgram(gl) {
  const program = gl.createProgram();
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program) ?? "program link failed");
  }
  return program;
}

function cssColor(name) {
  const hex = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) return [0.5, 0.5, 0.5];
  const n = Number.parseInt(match[1], 16);
  return [(n >> 16) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

function startBackground(canvas) {
  const gl = canvas.getContext("webgl", { antialias: false, alpha: false });
  if (!gl) return;

  const program = createProgram(gl);
  gl.useProgram(program);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, "aPosition");
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

  const uniform = (name) => gl.getUniformLocation(program, name);
  const u = {
    resolution: uniform("uResolution"),
    time: uniform("uTime"),
    bg: uniform("uBg"),
    ink: uniform("uInk"),
    accent: uniform("uAccent"),
    pulseColor: uniform("uPulseColor"),
    pulseOrigin: uniform("uPulseOrigin"),
    pulseAge: uniform("uPulseAge"),
    pulseKind: uniform("uPulseKind"),
  };

  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const darkScheme = matchMedia("(prefers-color-scheme: dark)");
  const pulse = { start: -IDLE_PULSE_AGE, origin: [0, 0] };
  let scale = 1;

  const applyTheme = () => {
    gl.uniform3fv(u.bg, cssColor("--bg"));
    gl.uniform3fv(u.ink, cssColor("--ink"));
    gl.uniform3fv(u.accent, cssColor("--accent"));
  };

  const resize = () => {
    scale = Math.min(devicePixelRatio || 1, MAX_PIXEL_RATIO);
    canvas.width = Math.round(innerWidth * scale);
    canvas.height = Math.round(innerHeight * scale);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(u.resolution, canvas.width, canvas.height);
  };

  const draw = (now) => {
    const seconds = now / 1000;
    gl.uniform1f(u.time, reducedMotion.matches ? 0 : seconds);
    gl.uniform1f(u.pulseAge, seconds - pulse.start);
    gl.uniform2fv(u.pulseOrigin, pulse.origin);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };

  const loop = (now) => {
    draw(now);
    requestAnimationFrame(loop);
  };

  const redrawStill = () => draw(performance.now());

  document.addEventListener("psr:round", (event) => {
    if (reducedMotion.matches) return;
    const { outcome, origin } = event.detail;
    const rect = origin.getBoundingClientRect();
    pulse.origin = [
      (rect.left + rect.width / 2) * scale,
      canvas.height - (rect.top + rect.height / 2) * scale,
    ];
    pulse.start = performance.now() / 1000;
    gl.uniform3fv(u.pulseColor, cssColor(`--${outcome}`));
    gl.uniform1f(u.pulseKind, PULSE_KINDS[outcome] ?? 0);
  });

  addEventListener("resize", () => {
    resize();
    redrawStill();
  });
  darkScheme.addEventListener("change", () => {
    applyTheme();
    redrawStill();
  });

  applyTheme();
  resize();
  canvas.classList.add("ready");
  if (reducedMotion.matches) redrawStill();
  else requestAnimationFrame(loop);
}

try {
  startBackground(document.getElementById("fx"));
} catch (error) {
  console.warn("Background effect disabled:", error);
}
