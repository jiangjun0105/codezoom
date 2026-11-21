import { useEffect } from "react";
import { Breadcrumb } from "./components/Breadcrumb";
import { Canvas } from "./components/Canvas";
import { Dock } from "./components/Dock";
import { Jump } from "./components/Jump";
import { Pyramid } from "./components/Pyramid";
import { Story } from "./components/Story";
import { graph } from "./lib/graph";
import { set, useStore } from "./store";

export const LINKS = {
  writeup: "https://www.junbot.dev/article/repo-understanding-tool",
  repo: "https://github.com/jiangjun0105/codezoom",
};

export default function App() {
  const dock = useStore((s) => s.dock);
  const driving = useStore((s) => s.driving);
  const mode = useStore((s) => s.mode);

  useEffect(() => {
    document.documentElement.classList.toggle("is-driving", driving);
  }, [driving]);

  // On the first screen the wheel only zooms: it never scrolls the page (the arrow below
  // the demo does). Panels inside still scroll while they have room to.
  useEffect(() => {
    const onWheel = (ev: WheelEvent) => {
      if (window.scrollY > 4 || ev.ctrlKey) return;
      const t = ev.target as HTMLElement;
      if (!t.closest?.(".stage")) return;
      for (let el: HTMLElement | null = t; el && !el.classList.contains("stage"); el = el.parentElement) {
        const style = getComputedStyle(el);
        if (!/(auto|scroll)/.test(style.overflowY) || el.scrollHeight <= el.clientHeight + 1) continue;
        const room = ev.deltaY > 0 ? el.scrollHeight - el.clientHeight - el.scrollTop > 1 : el.scrollTop > 0;
        if (room) return;
      }
      ev.preventDefault();
    };
    window.addEventListener("wheel", onWheel, { passive: false });
    return () => window.removeEventListener("wheel", onWheel);
  }, []);

  return (
    <>
      <header className="site-header">
        <a className="brand" href="#top">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
            <rect x="3" y="3" width="26" height="26" rx="5" fill="none" stroke="var(--line-3)" strokeWidth="2" />
            <rect x="9" y="9" width="14" height="14" rx="3" fill="none" stroke="var(--muted)" strokeWidth="2" />
            <rect x="13.500" y="13.500" width="5" height="5" rx="1.2" fill="var(--accent)" />
          </svg>
          Codezoom
        </a>
        <span className="badge">research prototype · since 2023</span>
        <nav>
          <a href="#how">How it works</a>
          <a href={LINKS.writeup} target="_blank" rel="noreferrer">Write-up</a>
          <a href={LINKS.repo} target="_blank" rel="noreferrer">GitHub</a>
        </nav>
      </header>

      <main id="top" className="stage">
        <div className="hero">
          <h1>A codebase you can zoom into.</h1>
          <p>
            {graph.meta.repo} {graph.meta.version}, mapped automatically from its source.
          </p>
        </div>

        <section className={`frame${dock ? " has-dock" : ""}`} aria-label="Interactive flowchart">
          <div className="bar">
            <Breadcrumb />
            <div className="bar-right">
              <span className="target">{graph.meta.repo} {graph.meta.version} · run_auto_gpt</span>
              <button className="search" onClick={() => set({ jump: true })} title="Jump to any step">
                Search <kbd>/</kbd>
              </button>
              <button className={mode === "space" ? "on" : ""} onClick={() => set({ mode: mode === "space" ? "flat" : "space", touched: true })} title="See every level at once, as a pyramid">
                3D
              </button>
              <button className={dock === "source" ? "on" : ""} onClick={() => set({ dock: dock === "source" ? null : "source" })}>Source</button>
              <button className={dock === "ask" ? "on" : ""} onClick={() => set({ dock: dock === "ask" ? null : "ask" })}>Ask</button>
            </div>
          </div>
          {mode === "space" ? <Pyramid /> : <Canvas />}
          <Dock />
          <Jump />
        </section>
        <a className="scroll-down" href="#how" aria-label="Scroll down to how it works">
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
            <path d="M7 2v9M2.5 7 7 11.5 11.5 7" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </a>
      </main>

      <Story />
    </>
  );
}
