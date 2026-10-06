import { useEffect, useRef } from "react";
import { useTheme } from "../lib/theme";
import { cx } from "./ui";

/**
 * A faint drifting line field: nodes that pass close to each other are joined by hairlines,
 * and nodes near the pointer join it in the brand colour. Adapted from ThreeUI's
 * "Constellation Field / Interface Lines" (MIT, github.com/MengTo/threeui).
 *
 * Colours come from the --field, --field-alpha and --field-accent tokens of the nearest
 * theme scope, so it also works inside a `.dark` panel on a light page. Fills its
 * positioned parent; it pauses while off screen or in a hidden tab, and draws a single
 * still frame for people who prefer reduced motion.
 */
export function InterfaceLines({
  className,
  density = 1,
  linkDistance = 120,
}: {
  className?: string;
  /** Nodes per area, relative to the default (about one per 16,000 px²). */
  density?: number;
  /** Nodes closer than this many CSS pixels are joined. */
  linkDistance?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const { dark } = useTheme();

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    const host = canvas?.parentElement;
    if (!canvas || !ctx || !host) return;

    const css = getComputedStyle(canvas);
    const ink = css.getPropertyValue("--field").trim() || "255 255 255";
    const accent = css.getPropertyValue("--field-accent").trim() || ink;
    const strength = Number.parseFloat(css.getPropertyValue("--field-alpha")) || 1;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;

    type Node = { x: number; y: number; vx: number; vy: number };
    let nodes: Node[] = [];
    let width = 0;
    let height = 0;
    let raf = 0;
    let last = 0;
    let onScreen = true;
    const pointer = { x: 0, y: 0, active: false };

    const seed = () => {
      const target = Math.round(Math.min(110, Math.max(18, ((width * height) / 16000) * density)));
      // Keep the nodes already on screen so a resize does not reshuffle the field.
      nodes = nodes.filter((n) => n.x <= width && n.y <= height).slice(0, target);
      while (nodes.length < target) {
        const angle = Math.random() * Math.PI * 2;
        const speed = 6 + Math.random() * 12; // px per second
        nodes.push({ x: Math.random() * width, y: Math.random() * height, vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed });
      }
    };

    const resize = () => {
      const rect = host.getBoundingClientRect();
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
      draw();
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);
      ctx.lineWidth = 1;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j];
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d < linkDistance) {
            ctx.strokeStyle = `rgb(${ink} / ${(0.07 + (1 - d / linkDistance) * 0.28) * strength})`;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
        if (pointer.active) {
          const d = Math.hypot(a.x - pointer.x, a.y - pointer.y);
          const reach = linkDistance * 1.4;
          if (d < reach) {
            ctx.strokeStyle = `rgb(${accent} / ${(1 - d / reach) * 0.6})`;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(pointer.x, pointer.y);
            ctx.stroke();
          }
        }
        ctx.fillStyle = `rgb(${ink} / ${0.55 * strength})`;
        ctx.fillRect(a.x - 0.75, a.y - 0.75, 1.5, 1.5);
      }
    };

    const step = (dt: number) => {
      for (const n of nodes) {
        n.x += n.vx * dt;
        n.y += n.vy * dt;
        if (n.x < 0 || n.x > width) n.vx *= -1;
        if (n.y < 0 || n.y > height) n.vy *= -1;
      }
    };

    const frame = (t: number) => {
      const dt = last ? Math.min((t - last) / 1000, 0.05) : 0;
      last = t;
      step(dt);
      draw();
      raf = requestAnimationFrame(frame);
    };

    const play = () => {
      if (still || raf || !onScreen || document.hidden) return;
      last = 0;
      raf = requestAnimationFrame(frame);
    };
    const pause = () => {
      cancelAnimationFrame(raf);
      raf = 0;
    };
    const sync = () => (onScreen && !document.hidden ? play() : pause());

    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      const rect = canvas.getBoundingClientRect();
      pointer.x = e.clientX - rect.left;
      pointer.y = e.clientY - rect.top;
      pointer.active = true;
      if (still) draw();
    };
    const onLeave = () => {
      pointer.active = false;
      if (still) draw();
    };

    const resizer = new ResizeObserver(resize);
    resizer.observe(host);
    const watcher = new IntersectionObserver(([entry]) => {
      onScreen = entry.isIntersecting;
      sync();
    });
    watcher.observe(canvas);
    document.addEventListener("visibilitychange", sync);
    host.addEventListener("pointermove", onMove);
    host.addEventListener("pointerleave", onLeave);
    resize();
    play();

    return () => {
      pause();
      resizer.disconnect();
      watcher.disconnect();
      document.removeEventListener("visibilitychange", sync);
      host.removeEventListener("pointermove", onMove);
      host.removeEventListener("pointerleave", onLeave);
    };
  }, [dark, density, linkDistance]);

  return <canvas ref={ref} aria-hidden="true" className={cx("pointer-events-none absolute inset-0 size-full", className)} />;
}
