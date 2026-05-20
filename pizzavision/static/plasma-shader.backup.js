/*
 * PIZZAVISION plasma background — ported from corners/apps/design/shader-plasma.
 *
 * Public API on window.PlasmaShader:
 *   triggerPulse(angle?)   radial pulse ring
 *   triggerBolt(angle?)    lightning bolt from focus to edge
 *   triggerTrace(angle?)   streaming directional trace
 *   triggerBgFlash()       full-screen luminance flash
 *   setFocus(x, y)         focal point in -0.5..0.5 normalized coords
 *   setColors({a, b, bg})  rgb triples in 0..1, override defaults
 */
(function () {
  "use strict";

  var VERTEX_SHADER_SOURCE = [
    "attribute vec2 position;",
    "void main() {",
    "  gl_Position = vec4(position, 0.0, 1.0);",
    "}",
  ].join("\n");

  var FRAGMENT_SHADER_SOURCE = [
    "precision highp float;",
    "",
    "#define MAX_TRACES 4",
    "#define MAX_PULSES 4",
    "#define MAX_BOLTS 4",
    "",
    "uniform vec2  u_resolution;",
    "uniform float u_time;",
    "",
    "uniform float u_focus_x;",
    "uniform float u_focus_y;",
    "",
    "uniform float u_angular_scale;",
    "uniform float u_radial_scale;",
    "uniform float u_warp_strength;",
    "uniform float u_anim_speed;",
    "",
    "uniform float u_discharge_sharpness;",
    "uniform float u_discharge_threshold;",
    "",
    "uniform float u_filament_intensity;",
    "uniform float u_filament_falloff;",
    "uniform float u_center_fade;",
    "",
    "uniform float u_bg_tint;",
    "",
    "uniform vec3 u_color_a;",
    "uniform vec3 u_color_b;",
    "uniform vec3 u_bg_color;",
    "",
    "uniform float u_trace_angles[MAX_TRACES];",
    "uniform float u_trace_times[MAX_TRACES];",
    "uniform float u_trace_duration;",
    "uniform float u_trace_intensity;",
    "",
    "uniform float u_pulse_angles[MAX_PULSES];",
    "uniform float u_pulse_times[MAX_PULSES];",
    "uniform float u_pulse_duration;",
    "uniform float u_pulse_intensity;",
    "",
    "uniform float u_bolt_angles[MAX_BOLTS];",
    "uniform float u_bolt_times[MAX_BOLTS];",
    "uniform float u_bolt_seeds[MAX_BOLTS];",
    "uniform float u_bolt_duration;",
    "uniform float u_bolt_intensity;",
    "",
    "uniform float u_bg_flash_time;",
    "uniform float u_bg_flash_peak;",
    "",
    "float hash(float n) { return fract(sin(n) * 1e4); }",
    "float hash(vec2 p) {",
    "  return fract(1e4 * sin(17.0 * p.x + p.y * 0.1) * (0.1 + abs(sin(p.y * 13.0 + p.x))));",
    "}",
    "",
    "float noise(vec3 x) {",
    "  const vec3 step = vec3(110.0, 241.0, 171.0);",
    "  vec3 i = floor(x);",
    "  vec3 f = fract(x);",
    "  float n = dot(i, step);",
    "  vec3 u = f * f * (3.0 - 2.0 * f);",
    "  return mix(",
    "    mix(",
    "      mix(hash(n + dot(step, vec3(0,0,0))), hash(n + dot(step, vec3(1,0,0))), u.x),",
    "      mix(hash(n + dot(step, vec3(0,1,0))), hash(n + dot(step, vec3(1,1,0))), u.x),",
    "      u.y",
    "    ),",
    "    mix(",
    "      mix(hash(n + dot(step, vec3(0,0,1))), hash(n + dot(step, vec3(1,0,1))), u.x),",
    "      mix(hash(n + dot(step, vec3(0,1,1))), hash(n + dot(step, vec3(1,1,1))), u.x),",
    "      u.y",
    "    ),",
    "    u.z",
    "  );",
    "}",
    "",
    "float fbm(vec3 p) {",
    "  float value = 0.0;",
    "  float amplitude = 0.5;",
    "  for (int i = 0; i < 5; i++) {",
    "    value += amplitude * noise(p);",
    "    p *= 2.0;",
    "    amplitude *= 0.5;",
    "  }",
    "  return value;",
    "}",
    "",
    "vec3 screenBlend(vec3 base, vec3 blend) {",
    "  return 1.0 - (1.0 - base) * (1.0 - blend);",
    "}",
    "",
    "float wrapAngleDist(float a, float b) {",
    "  float d = a - b;",
    "  return abs(d - 6.28318530 * floor((d + 3.14159265) / 6.28318530));",
    "}",
    "",
    "void main() {",
    "  vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution.xy) / min(u_resolution.x, u_resolution.y);",
    "",
    "  vec2 focusPos = vec2(u_focus_x, u_focus_y);",
    "  vec2 delta = uv - focusPos;",
    "  float r = length(delta);",
    "  float theta = atan(delta.y, delta.x);",
    "",
    "  float thetaNorm = (theta + 3.14159265) / 6.28318530;",
    "  vec2 polarUV = vec2(thetaNorm * u_angular_scale, r * u_radial_scale);",
    "",
    "  float t = u_time * u_anim_speed;",
    "",
    "  float skeleton = fbm(vec3(thetaNorm * u_angular_scale, r * 0.5, t * 0.7));",
    "",
    "  vec2 q = vec2(",
    "    fbm(vec3(polarUV * 1.0, t)),",
    "    fbm(vec3(polarUV * 1.0 + vec2(5.2, 1.3), t * 0.8))",
    "  );",
    "  vec2 rr = vec2(",
    "    fbm(vec3(polarUV * 2.0 + q * u_warp_strength, t * 1.2)),",
    "    fbm(vec3(polarUV * 2.0 + q * u_warp_strength + vec2(2.3, 4.1), t * 1.5))",
    "  );",
    "  float organic = fbm(vec3(polarUV * 1.5 + rr * u_warp_strength * 0.7, t));",
    "",
    "  float n = mix(skeleton, organic, 0.38);",
    "",
    "  float discharge = u_discharge_sharpness / abs(n - u_discharge_threshold);",
    "  discharge = min(discharge, 10.0);",
    "",
    "  float streamerFalloff = exp(-r * u_filament_falloff);",
    "  float originFade = smoothstep(0.0, u_center_fade, r);",
    "",
    "  float intensity = discharge * streamerFalloff * originFade * u_filament_intensity;",
    "",
    "  float traceBoost = 0.0;",
    "  float traceAngW = 0.3;",
    "  float maxReach = 1.8;",
    "  for (int i = 0; i < MAX_TRACES; i++) {",
    "    if (u_trace_times[i] < 0.0) continue;",
    "    float prog = clamp(u_trace_times[i] / max(u_trace_duration, 0.001), 0.0, 1.0);",
    "    float aDiff = wrapAngleDist(theta, u_trace_angles[i]);",
    "    float aMask = smoothstep(traceAngW, traceAngW * 0.12, aDiff);",
    "    float reachR = prog * maxReach;",
    "    float behind = step(r, reachR);",
    "    float front = exp(-(reachR - r) * 10.0);",
    "    float rMask = behind * (0.25 + 0.75 * front);",
    "    float gate = smoothstep(0.08, 0.35, clamp(discharge / 5.0, 0.0, 1.0));",
    "    float env = smoothstep(0.0, 0.02, prog) * (1.0 - smoothstep(0.82, 1.0, prog));",
    "    traceBoost += aMask * gate * rMask * env * u_trace_intensity * originFade;",
    "  }",
    "",
    "  float pulseBoost = 0.0;",
    "  float pulseAngW = 0.6;",
    "  for (int i = 0; i < MAX_PULSES; i++) {",
    "    if (u_pulse_times[i] < 0.0) continue;",
    "    float prog = clamp(u_pulse_times[i] / max(u_pulse_duration, 0.001), 0.0, 1.0);",
    "    float aDiff = wrapAngleDist(theta, u_pulse_angles[i]);",
    "    float aMask = smoothstep(pulseAngW, pulseAngW * 0.18, aDiff);",
    "    float ringR = prog * maxReach;",
    "    float ringW = 0.06 + prog * 0.08;",
    "    float ring = smoothstep(ringW, 0.0, abs(r - ringR));",
    "    float env = smoothstep(0.0, 0.02, prog) * (1.0 - smoothstep(0.55, 1.0, prog));",
    "    pulseBoost += discharge * ring * aMask * env * u_pulse_intensity * originFade;",
    "  }",
    "",
    "  float boltBoost = 0.0;",
    "  float boltCore = 0.007;",
    "  float boltGlow = 0.035;",
    "  for (int i = 0; i < MAX_BOLTS; i++) {",
    "    if (u_bolt_times[i] < 0.0) continue;",
    "    float prog = clamp(u_bolt_times[i] / max(u_bolt_duration, 0.001), 0.0, 1.0);",
    "",
    "    vec2 bDir = vec2(cos(u_bolt_angles[i]), sin(u_bolt_angles[i]));",
    "    vec2 bPerp = vec2(-bDir.y, bDir.x);",
    "    float along = dot(delta, bDir);",
    "    float perp = dot(delta, bPerp);",
    "",
    "    if (along > 0.0) {",
    "      float seed = u_bolt_seeds[i];",
    "      float w1 = (fbm(vec3(along * 4.0, seed, 0.0)) - 0.5) * 0.18;",
    "      float w2 = (noise(vec3(along * 15.0, seed + 73.0, 0.0)) - 0.5) * 0.06;",
    "      float wiggle = (w1 + w2) * along;",
    "",
    "      float dist = abs(perp - wiggle);",
    "",
    "      float core = smoothstep(boltCore, boltCore * 0.08, dist);",
    "      float glow = exp(-dist / boltGlow);",
    "",
    "      float reach = min(prog * 5.0, 1.0) * maxReach;",
    "      float reachMask = smoothstep(reach, reach - 0.06, along);",
    "",
    "      float env = (1.0 - smoothstep(0.25, 1.0, prog));",
    "",
    "      boltBoost += (core + glow * 0.35) * reachMask * env * u_bolt_intensity;",
    "    }",
    "  }",
    "",
    "  float bgBoost = 0.0;",
    "  if (u_bg_flash_time >= 0.0) {",
    "    float ft = clamp(u_bg_flash_time / max(u_pulse_duration, 0.001), 0.0, 1.0);",
    "    bgBoost = smoothstep(0.0, 0.08, ft) * (1.0 - smoothstep(0.08, 1.0, ft)) * u_bg_flash_peak;",
    "  }",
    "",
    "  float eff = intensity + traceBoost + pulseBoost + boltBoost + u_bg_tint + bgBoost;",
    "",
    "  float bgLuma = dot(u_bg_color, vec3(0.2126, 0.7152, 0.0722));",
    "  float isLight = smoothstep(0.42, 0.92, bgLuma);",
    "",
    "  vec3 palA = mix(u_color_a, vec3(1.0) - u_color_a, isLight);",
    "  vec3 palB = mix(u_color_b, vec3(1.0) - u_color_b, isLight);",
    "  vec3 base = mix(u_bg_color, vec3(1.0) - u_bg_color, isLight);",
    "",
    "  float weightA = smoothstep(0.5, -0.5, uv.x + uv.y) * eff;",
    "  float weightB = smoothstep(-0.5, 0.5, uv.x + uv.y) * eff;",
    "",
    "  vec3 plasma = vec3(0.0);",
    "  plasma += palA * weightA * 1.5;",
    "  plasma += palB * weightB * 1.5;",
    "",
    "  float coreMask = smoothstep(0.4, 0.0, r) * eff * 0.5;",
    "  plasma += vec3(1.0) * coreMask;",
    "",
    "  float colorShift = 0.5 + 0.3 * sin(u_time * 0.08 + n * 2.0);",
    "  plasma += mix(palA, palB, colorShift) * originFade * n * 0.2;",
    "",
    "  plasma = pow(plasma, vec3(1.2));",
    "  plasma = clamp(plasma, 0.0, 1.0);",
    "",
    "  vec3 scene = screenBlend(base, plasma);",
    "  vec3 color = mix(scene, vec3(1.0) - scene, isLight);",
    "  color = mix(u_bg_color, color, mix(1.0, 0.94, isLight));",
    "",
    "  float vignette = smoothstep(1.6, 0.2, r);",
    "  color *= mix(0.72, 1.0, vignette);",
    "",
    "  gl_FragColor = vec4(color, 1.0);",
    "}",
  ].join("\n");

  var MAX_TRACES = 4;
  var MAX_PULSES = 4;
  var MAX_BOLTS = 4;
  var TARGET_FRAME_MS = 1000 / 30;

  // Eurovision stage-show feel: rays-from-below + sparser, dimmer plasma so
  // the page content stays readable; the discharge lines read as stage lasers,
  // the sparkle layer (added in the fragment shader) reads as pyro / glitter.
  var PARAMS = {
    focusX: 0.0,
    focusY: -0.55,
    angularScale: 14.0,
    radialScale: 3.0,
    warpStrength: 1.5,
    animSpeed: 0.02,
    dischargeSharpness: 0.015,
    dischargeThreshold: 0.5,
    filamentIntensity: 0.65,
    filamentFalloff: 1.1,
    centerFade: 0.06,
    bgTint: 0.02,
    traceDuration: 0.8,
    traceIntensity: 4.0,
    pulseDuration: 0.6,
    pulseIntensity: 3.0,
    boltDuration: 0.6,
    boltIntensity: 5.0,
    bgFlashPeak: 0.12,
  };

  // Stage-light palette: hot magenta + electric cyan on a deep blue-black.
  var COLORS = {
    a: [1.000, 0.169, 0.839], // #ff2bd6 magenta
    b: [0.000, 0.878, 1.000], // #00e0ff cyan
    bg: [0.024, 0.027, 0.071], // #06071a deep blue-black
  };

  var traces = [];
  var pulses = [];
  var bolts = [];
  var bgFlashStart = -1;

  function pickVisibleAngle() {
    return Math.PI * 0.5 + (Math.random() - 0.5) * Math.PI * 1.4;
  }

  function compileShader(gl, type, source) {
    var shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      var log = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error("Shader compile failed: " + log);
    }
    return shader;
  }

  function linkProgram(gl, vs, fs) {
    var program = gl.createProgram();
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      var log = gl.getProgramInfoLog(program);
      gl.deleteProgram(program);
      throw new Error("Program link failed: " + log);
    }
    return program;
  }

  function ensureCanvas() {
    var canvas = document.getElementById("pv-plasma-bg");
    if (!canvas) {
      canvas = document.createElement("canvas");
      canvas.id = "pv-plasma-bg";
      // Insert as the first body child so z-index:-1 puts it behind everything.
      if (document.body.firstChild) {
        document.body.insertBefore(canvas, document.body.firstChild);
      } else {
        document.body.appendChild(canvas);
      }
    }
    var s = canvas.style;
    s.position = "fixed";
    s.top = "0";
    s.left = "0";
    s.width = "100%";
    s.height = "100%";
    s.display = "block";
    s.zIndex = "-1";
    s.pointerEvents = "none";
    return canvas;
  }

  function init() {
    var canvas = ensureCanvas();
    var gl;
    try {
      gl = canvas.getContext("webgl", {
        alpha: false,
        antialias: false,
        depth: false,
        powerPreference: "low-power",
        premultipliedAlpha: false,
        preserveDrawingBuffer: false,
      });
    } catch (err) {
      gl = null;
    }
    if (!gl) {
      // Leave the page background showing through.
      canvas.parentNode && canvas.parentNode.removeChild(canvas);
      installNoopApi();
      return;
    }

    var vs, fs, program;
    try {
      vs = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER_SOURCE);
      fs = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER_SOURCE);
      program = linkProgram(gl, vs, fs);
    } catch (err) {
      console.error("[plasma-shader]", err);
      canvas.parentNode && canvas.parentNode.removeChild(canvas);
      installNoopApi();
      return;
    }

    gl.useProgram(program);

    var buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW
    );
    var posLoc = gl.getAttribLocation(program, "position");
    gl.enableVertexAttribArray(posLoc);
    gl.vertexAttribPointer(posLoc, 2, gl.FLOAT, false, 0, 0);

    function u(name) {
      return gl.getUniformLocation(program, name);
    }

    var locs = {
      resolution: u("u_resolution"),
      time: u("u_time"),
      focusX: u("u_focus_x"),
      focusY: u("u_focus_y"),
      angularScale: u("u_angular_scale"),
      radialScale: u("u_radial_scale"),
      warpStrength: u("u_warp_strength"),
      animSpeed: u("u_anim_speed"),
      dischargeSharpness: u("u_discharge_sharpness"),
      dischargeThreshold: u("u_discharge_threshold"),
      filamentIntensity: u("u_filament_intensity"),
      filamentFalloff: u("u_filament_falloff"),
      centerFade: u("u_center_fade"),
      bgTint: u("u_bg_tint"),
      traceAngles: u("u_trace_angles"),
      traceTimes: u("u_trace_times"),
      traceDuration: u("u_trace_duration"),
      traceIntensity: u("u_trace_intensity"),
      pulseAngles: u("u_pulse_angles"),
      pulseTimes: u("u_pulse_times"),
      pulseDuration: u("u_pulse_duration"),
      pulseIntensity: u("u_pulse_intensity"),
      boltAngles: u("u_bolt_angles"),
      boltTimes: u("u_bolt_times"),
      boltSeeds: u("u_bolt_seeds"),
      boltDuration: u("u_bolt_duration"),
      boltIntensity: u("u_bolt_intensity"),
      bgFlashTime: u("u_bg_flash_time"),
      bgFlashPeak: u("u_bg_flash_peak"),
      colorA: u("u_color_a"),
      colorB: u("u_color_b"),
      bgColor: u("u_bg_color"),
    };

    var traceABuf = new Float32Array(MAX_TRACES);
    var traceTBuf = new Float32Array(MAX_TRACES);
    var pulseABuf = new Float32Array(MAX_PULSES);
    var pulseTBuf = new Float32Array(MAX_PULSES);
    var boltABuf = new Float32Array(MAX_BOLTS);
    var boltTBuf = new Float32Array(MAX_BOLTS);
    var boltSBuf = new Float32Array(MAX_BOLTS);

    var disposed = false;
    var animFrame = 0;
    var lastDrawTime = -TARGET_FRAME_MS;
    var shaderTime = 0;
    var lastFrameTs = -1;
    var maxDelta = TARGET_FRAME_MS * 2;

    function fillBuf(aBuf, tBuf, list, max, now) {
      for (var i = 0; i < max; i++) {
        if (i < list.length) {
          aBuf[i] = list[i].angle;
          tBuf[i] = now - list[i].startTime;
        } else {
          aBuf[i] = 0;
          tBuf[i] = -1.0;
        }
      }
    }

    function draw(wallMs) {
      if (disposed) return;
      if (lastFrameTs >= 0) {
        shaderTime += Math.min(wallMs - lastFrameTs, maxDelta);
      }
      lastFrameTs = wallMs;

      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var w = Math.floor(canvas.clientWidth * dpr);
      var h = Math.floor(canvas.clientHeight * dpr);
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(locs.resolution, canvas.width, canvas.height);
      gl.uniform1f(locs.time, shaderTime * 0.001);

      gl.uniform1f(locs.focusX, PARAMS.focusX);
      gl.uniform1f(locs.focusY, PARAMS.focusY);
      gl.uniform1f(locs.angularScale, PARAMS.angularScale);
      gl.uniform1f(locs.radialScale, PARAMS.radialScale);
      gl.uniform1f(locs.warpStrength, PARAMS.warpStrength);
      gl.uniform1f(locs.animSpeed, PARAMS.animSpeed);
      gl.uniform1f(locs.dischargeSharpness, PARAMS.dischargeSharpness);
      gl.uniform1f(locs.dischargeThreshold, PARAMS.dischargeThreshold);
      gl.uniform1f(locs.filamentIntensity, PARAMS.filamentIntensity);
      gl.uniform1f(locs.filamentFalloff, PARAMS.filamentFalloff);
      gl.uniform1f(locs.centerFade, PARAMS.centerFade);
      gl.uniform1f(locs.bgTint, PARAMS.bgTint);

      gl.uniform3f(locs.colorA, COLORS.a[0], COLORS.a[1], COLORS.a[2]);
      gl.uniform3f(locs.colorB, COLORS.b[0], COLORS.b[1], COLORS.b[2]);
      gl.uniform3f(locs.bgColor, COLORS.bg[0], COLORS.bg[1], COLORS.bg[2]);

      var now = performance.now() / 1000;

      fillBuf(traceABuf, traceTBuf, traces, MAX_TRACES, now);
      gl.uniform1fv(locs.traceAngles, traceABuf);
      gl.uniform1fv(locs.traceTimes, traceTBuf);
      gl.uniform1f(locs.traceDuration, PARAMS.traceDuration);
      gl.uniform1f(locs.traceIntensity, PARAMS.traceIntensity);

      fillBuf(pulseABuf, pulseTBuf, pulses, MAX_PULSES, now);
      gl.uniform1fv(locs.pulseAngles, pulseABuf);
      gl.uniform1fv(locs.pulseTimes, pulseTBuf);
      gl.uniform1f(locs.pulseDuration, PARAMS.pulseDuration);
      gl.uniform1f(locs.pulseIntensity, PARAMS.pulseIntensity);

      for (var i = 0; i < MAX_BOLTS; i++) {
        if (i < bolts.length) {
          boltABuf[i] = bolts[i].angle;
          boltTBuf[i] = now - bolts[i].startTime;
          boltSBuf[i] = bolts[i].seed;
        } else {
          boltABuf[i] = 0;
          boltTBuf[i] = -1.0;
          boltSBuf[i] = 0;
        }
      }
      gl.uniform1fv(locs.boltAngles, boltABuf);
      gl.uniform1fv(locs.boltTimes, boltTBuf);
      gl.uniform1fv(locs.boltSeeds, boltSBuf);
      gl.uniform1f(locs.boltDuration, PARAMS.boltDuration);
      gl.uniform1f(locs.boltIntensity, PARAMS.boltIntensity);

      var bgElapsed = bgFlashStart >= 0 ? now - bgFlashStart : -1;
      gl.uniform1f(locs.bgFlashTime, bgElapsed);
      gl.uniform1f(locs.bgFlashPeak, PARAMS.bgFlashPeak);

      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }

    function render(wallMs) {
      if (disposed || document.hidden) return;
      if (wallMs - lastDrawTime >= TARGET_FRAME_MS) {
        lastDrawTime = wallMs;
        draw(wallMs);
      }
      if (!disposed) animFrame = window.requestAnimationFrame(render);
    }

    function handleVis() {
      if (!document.hidden) {
        lastFrameTs = performance.now();
        animFrame = window.requestAnimationFrame(render);
      }
    }

    document.addEventListener("visibilitychange", handleVis);
    animFrame = window.requestAnimationFrame(render);

    var cleanup = setInterval(function () {
      var t = performance.now() / 1000;
      traces = traces.filter(function (f) {
        return t - f.startTime < PARAMS.traceDuration + 0.05;
      });
      pulses = pulses.filter(function (f) {
        return t - f.startTime < PARAMS.pulseDuration + 0.05;
      });
      bolts = bolts.filter(function (f) {
        return t - f.startTime < PARAMS.boltDuration + 0.05;
      });
      if (
        bgFlashStart >= 0 &&
        t - bgFlashStart >= PARAMS.pulseDuration + 0.05
      ) {
        bgFlashStart = -1;
      }
    }, 300);

    window.addEventListener("beforeunload", function () {
      disposed = true;
      window.cancelAnimationFrame(animFrame);
      document.removeEventListener("visibilitychange", handleVis);
      clearInterval(cleanup);
    });

  }

  function installApi() {
    window.PlasmaShader = {
      triggerTrace: function (angle) {
        var now = performance.now() / 1000;
        traces.push({
          angle: typeof angle === "number" ? angle : pickVisibleAngle(),
          startTime: now,
        });
        if (traces.length > MAX_TRACES) traces.shift();
      },
      triggerPulse: function (angle) {
        var now = performance.now() / 1000;
        pulses.push({
          angle: typeof angle === "number" ? angle : pickVisibleAngle(),
          startTime: now,
        });
        if (pulses.length > MAX_PULSES) pulses.shift();
      },
      triggerBolt: function (angle) {
        var now = performance.now() / 1000;
        bolts.push({
          angle: typeof angle === "number" ? angle : pickVisibleAngle(),
          startTime: now,
          seed: Math.random() * 1000,
        });
        if (bolts.length > MAX_BOLTS) bolts.shift();
      },
      triggerBgFlash: function () {
        bgFlashStart = performance.now() / 1000;
      },
      setFocus: function (x, y) {
        if (typeof x === "number") PARAMS.focusX = x;
        if (typeof y === "number") PARAMS.focusY = y;
      },
      setColors: function (c) {
        if (!c) return;
        if (c.a) COLORS.a = c.a;
        if (c.b) COLORS.b = c.b;
        if (c.bg) COLORS.bg = c.bg;
      },
    };
  }

  function installNoopApi() {
    var noop = function () {};
    window.PlasmaShader = {
      triggerTrace: noop,
      triggerPulse: noop,
      triggerBolt: noop,
      triggerBgFlash: noop,
      setFocus: noop,
      setColors: noop,
    };
  }

  // Install the API synchronously so inline <script> blocks loaded after this
  // file can register handlers that reference window.PlasmaShader before
  // DOMContentLoaded — the methods just push to module-scoped queues that
  // init() reads from once the canvas is up.
  installApi();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
