/* Port of NVIDIA DGX OOBE nv-nebula canvas (sphere variant). Vanilla JS. */
(function (global) {
  'use strict';

  const DT = 0.02;
  const SIZE_LERP = 0.02;
  const PARTICLE_COUNT = 250;

  const rand = (a, b) => Math.random() * (b - a) + a;
  const lerp = (a, b, t) => a + (b - a) * t;
  const easeOut = (t) => t * t * t;

  function pickKind() {
    const s = Math.random();
    if (s < 0.7) return 'small';
    if (s < 0.9) return 'gold';
    return 'gold-large';
  }

  function pickRadius(kind) {
    if (kind === 'small') return rand(1, 2);
    if (kind === 'gold') return rand(2, 3);
    return rand(2.5, 3.5);
  }

  function pickSpin(kind) {
    if (kind === 'small') return rand(0.05, 0.1);
    if (kind === 'gold') return rand(0.03, 0.08);
    return rand(0.01, 0.04);
  }

  class BaseParticle {
    constructor(speedMult, kind) {
      this.speedMult = speedMult;
      this.kind = kind || pickKind();
      this.radius = pickRadius(this.kind);
      this.spinSpeed = pickSpin(this.kind);
      this.spinAngle = 0;
      this.x = 0;
      this.y = 0;
      this.fade = 1;
    }

    fillStyle(state) {
      const b = state.brightness != null ? state.brightness : 1;
      if (this.kind === 'small') {
        const a = (state.particleAlpha != null ? state.particleAlpha : 0.3) * b;
        return 'rgba(255, 255, 255, ' + Math.min(a, 1) + ')';
      }
      const g = (state.goldBrightness != null ? state.goldBrightness : 1) * b;
      return 'rgba(223, 181, 95, ' + Math.min(g, 1) + ')';
    }

    draw(ctx, state) {
      ctx.save();
      ctx.translate(this.x, this.y);
      ctx.rotate(this.spinAngle);
      ctx.globalAlpha = this.fade;
      ctx.beginPath();
      ctx.arc(0, 0, this.radius, 0, Math.PI * 2);
      ctx.fillStyle = this.fillStyle(state);
      ctx.fill();
      ctx.restore();
    }
  }

  class OrbitParticle extends BaseParticle {
    constructor(center, sphereScale, speedMult) {
      super(speedMult);
      this.center = center;
      this.x = center.x;
      this.y = center.y;
      this.orbitVelocity = 0.001;
      this.fade = 0;
      this.radians = Math.random() * Math.PI * 2;
      this.originalDistance = {
        x: rand(40, 70) * sphereScale,
        y: rand(40, 70) * sphereScale,
      };
      this.distanceFromCenter = { x: this.originalDistance.x, y: this.originalDistance.y };
    }

    update(step) {
      const s = this.speedMult;
      if (this.fade < 1) this.fade = Math.min(1, this.fade + step * s);
      this.radians += this.orbitVelocity * s;
      this.x = this.center.x + Math.cos(this.radians) * this.distanceFromCenter.x;
      this.y = this.center.y + Math.sin(this.radians) * this.distanceFromCenter.y;
      this.spinAngle += this.spinSpeed * s;
    }

    scaleOrbit(center, scale) {
      this.center = center;
      this.originalDistance.x *= scale;
      this.originalDistance.y *= scale;
      this.distanceFromCenter.x = this.originalDistance.x;
      this.distanceFromCenter.y = this.originalDistance.y;
    }
  }

  function lineStroke(color, alpha) {
    return color.replace(/[\d.]+\)$/g, alpha + ')');
  }

  function drawLinks(ctx, particles, fromIdx, maxDist, state) {
    const lineA = state.lineAlpha != null ? state.lineAlpha : 0.15;
    for (let j = fromIdx + 1; j < particles.length; j++) {
      const a = particles[fromIdx];
      const b = particles[j];
      if (!a || !b) continue;
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      if (Math.sqrt(dx * dx + dy * dy) < maxDist) {
        const stroke = Math.random() < 0.5 ? a.fillStyle(state) : b.fillStyle(state);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = lineStroke(stroke, lineA);
        ctx.lineWidth = 0.4;
        ctx.stroke();
      }
    }
  }

  function nebulaSize(canvas) {
    const parent = canvas.parentElement;
    let w = parent ? parent.clientWidth : 0;
    let h = parent ? parent.clientHeight : 0;
    if (!w || !h) {
      const shell = canvas.closest('.page-shell, .shell');
      if (shell) {
        w = shell.clientWidth;
        h = shell.clientHeight;
      }
    }
    if (!w || !h) {
      w = document.documentElement.clientWidth;
      h = document.documentElement.clientHeight;
    }
    return { w: Math.max(w, 1), h: Math.max(h, 1) };
  }

  function resizeState(state) {
    if (!state.ctx || !state.canvas) return;
    const { w, h } = nebulaSize(state.canvas);
    state.canvas.width = w;
    state.canvas.height = h;
    const targetY = state.yFrac != null
      ? state.canvas.height * state.yFrac
      : (state.yOffset != null ? state.yOffset : state.canvas.height / 2);
    if (state.lastYOffset == null) state.lastYOffset = targetY;
    state.yOffset = targetY;
    state.center = {
      x: state.xOffset != null ? state.xOffset : state.canvas.width / 2,
      y: state.lastYOffset,
    };
  }

  function updateScrim(state) {
    if (!state.scrimEl) return;
    const contrast = state.contrast != null ? state.contrast : 1;
    const center = Math.min(0.5, (state.scrimCenter != null ? state.scrimCenter : 0.1) / contrast);
    const edge = Math.min(0.98, state.scrimDark != null ? state.scrimDark : 0.82);
    const mid = lerp(center, edge, 0.65);
    state.scrimEl.style.background =
      'radial-gradient(ellipse 70% 55% at 50% 42%, rgba(0, 0, 0, ' + center + ') 0%, rgba(0, 0, 0, ' + mid + ') 65%, rgba(0, 0, 0, ' + edge + ') 100%)';
  }

  function frame(state) {
    if (!state.ctx || !state.canvas || !state.running) return;
    resizeState(state);

    const ctx = state.ctx;
    ctx.clearRect(0, 0, state.canvas.width, state.canvas.height);

    let scaleRatio = 1;
    if (state.yOffset != null && state.lastYOffset != null && Math.abs(state.yOffset - state.lastYOffset) > 0.1) {
      state.lastYOffset = lerp(state.lastYOffset, state.yOffset, easeOut(0.35));
    }
    if (Math.abs(state.sphereSize - state.lastSphereSize) > 0.1) {
      const next = lerp(state.lastSphereSize, state.sphereSize, SIZE_LERP);
      scaleRatio = next / state.lastSphereSize;
      state.lastSphereSize = next;
    }

    const linkDist = state.lastSphereSize * 1.2;
    state.particles.forEach((p, idx) => {
      drawLinks(ctx, state.particles, idx, linkDist, state);
      p.scaleOrbit(state.center, scaleRatio);
      p.update(DT);
      p.draw(ctx, state);
    });

    state.raf = requestAnimationFrame(() => frame(state));
  }

  function defaultState(options) {
    options = options || {};
    return {
      speed: 0.1,
      brightness: 2,
      contrast: 0.95,
      sphereSize: 135,
      yFrac: 0.42,
      lineAlpha: 0.35,
      scrimDark: 0.44,
      scrimCenter: 0.13,
      particleAlpha: 0.22,
      goldBrightness: 1,
    };
  }

  function SparkyNebula(canvas, options) {
    options = options || {};
    const defs = defaultState(options);
    this.state = {
      canvas,
      scrimEl: options.scrimEl || (canvas.parentElement && canvas.parentElement.querySelector('.scrim')),
      ctx: null,
      particles: [],
      center: { x: 0, y: 0 },
      xOffset: options.xOffset,
      yOffset: options.yOffset,
      yFrac: options.yFrac != null ? options.yFrac : defs.yFrac,
      lastYOffset: options.yOffset,
      sphereSize: options.sphereSize != null ? options.sphereSize : defs.sphereSize,
      lastSphereSize: options.sphereSize != null ? options.sphereSize : defs.sphereSize,
      speed: options.speed != null ? options.speed : defs.speed,
      brightness: options.brightness != null ? options.brightness : defs.brightness,
      contrast: options.contrast != null ? options.contrast : defs.contrast,
      lineAlpha: options.lineAlpha != null ? options.lineAlpha : defs.lineAlpha,
      scrimDark: options.scrimDark != null ? options.scrimDark : defs.scrimDark,
      scrimCenter: options.scrimCenter != null ? options.scrimCenter : defs.scrimCenter,
      particleAlpha: options.particleAlpha != null ? options.particleAlpha : defs.particleAlpha,
      goldBrightness: options.goldBrightness != null ? options.goldBrightness : defs.goldBrightness,
      running: false,
      raf: 0,
    };
    this._resizeObserver = null;
    updateScrim(this.state);
  }

  SparkyNebula.prototype.setOptions = function (opts) {
    if (!opts) return;
    const state = this.state;
    if (opts.speed != null) {
      state.speed = opts.speed;
      state.particles.forEach((p) => { p.speedMult = opts.speed; });
    }
    if (opts.sphereSize != null) state.sphereSize = opts.sphereSize;
    if (opts.yFrac != null) state.yFrac = opts.yFrac;
    if (opts.brightness != null) state.brightness = opts.brightness;
    if (opts.contrast != null) state.contrast = opts.contrast;
    if (opts.lineAlpha != null) state.lineAlpha = opts.lineAlpha;
    if (opts.scrimDark != null) state.scrimDark = opts.scrimDark;
    if (opts.scrimCenter != null) state.scrimCenter = opts.scrimCenter;
    if (opts.particleAlpha != null) state.particleAlpha = opts.particleAlpha;
    if (opts.goldBrightness != null) state.goldBrightness = opts.goldBrightness;
    updateScrim(state);
  };

  SparkyNebula.prototype.getOptions = function () {
    const s = this.state;
    return {
      speed: s.speed,
      brightness: s.brightness,
      contrast: s.contrast,
      sphereSize: s.sphereSize,
      yFrac: s.yFrac,
      lineAlpha: s.lineAlpha,
      scrimDark: s.scrimDark,
      scrimCenter: s.scrimCenter,
      particleAlpha: s.particleAlpha,
      goldBrightness: s.goldBrightness,
    };
  };

  SparkyNebula.prototype.start = function () {
    const state = this.state;
    if (state.running) return;
    state.ctx = state.canvas.getContext('2d', { alpha: true });
    state.particles = [];
    const scale = state.sphereSize / 10;
    resizeState(state);
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      state.particles.push(new OrbitParticle(state.center, scale, state.speed));
    }
    state.running = true;
    frame(state);

    if (typeof ResizeObserver !== 'undefined' && state.canvas.parentElement) {
      this._resizeObserver = new ResizeObserver(() => resizeState(state));
      this._resizeObserver.observe(state.canvas.parentElement);
    }
  };

  SparkyNebula.prototype.stop = function () {
    const state = this.state;
    state.running = false;
    if (state.raf) cancelAnimationFrame(state.raf);
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
  };

  global.SparkyNebula = SparkyNebula;
})(window);