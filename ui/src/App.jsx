import { EnvironmentCanvas } from "./components/EnvironmentCanvas";
import { PreviewBox } from "./components/PreviewBox";
import { HUD, CompactHUD } from "./components/HUD";
import { ChatRail } from "./components/ChatRail";
import { useViewport } from "./hooks/useViewport";
import { useDelphiStore } from "./store/delphiStore";

/**
 * App — adaptive shell.
 *
 * Same component tree for every device class. Layout switches on the
 * viewport tier (see `useViewport`):
 *
 *   tiny / phone   → chat-first vertical stack with a compact HUD strip
 *   pi             → two-zone landscape: preview + chat, mode pill in corner
 *   laptop/desktop → full three-zone JARVIS layout
 */
function App() {
  const tier = useViewport();
  const compact = tier === "tiny" || tier === "phone";
  const landscape = tier === "pi";

  return (
    <div
      className={[
        "grid h-full w-full gap-2 p-2",
        compact ? "grid-rows-[auto_1fr]" : "sm:gap-3 sm:p-3 grid-rows-[1fr_auto]",
      ].join(" ")}
    >
      {compact ? (
        <>
          <CompactHUD />
          <ChatRail />
        </>
      ) : (
        <>
          <div className="relative min-h-0">
            <EnvironmentCanvas>
              <div
                className={[
                  "grid h-full w-full gap-3 p-3 md:gap-4 md:p-4",
                  landscape
                    ? "grid-cols-1 grid-rows-[auto_1fr]"
                    : "grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]",
                ].join(" ")}
              >
                <div className="flex min-h-0 flex-col gap-3 md:gap-4">
                  <TitleBar landscape={landscape} />
                  <div className="min-h-0 flex-1">
                    <PreviewBox />
                  </div>
                </div>
                {!landscape && (
                  <div className="flex flex-col gap-4">
                    <HUD />
                  </div>
                )}
              </div>
            </EnvironmentCanvas>
            {landscape && <CornerMode />}
          </div>
          <div className={landscape ? "h-40" : "h-56 lg:h-64"}>
            <ChatRail />
          </div>
        </>
      )}
    </div>
  );
}

function TitleBar({ landscape }) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-baseline gap-3">
        <h1
          className={[
            "font-display tracking-[0.5em] text-[var(--color-accent-cyan)] text-glow-cyan",
            landscape ? "text-lg" : "text-xl lg:text-2xl",
          ].join(" ")}
        >
          DELPHI
        </h1>
        <span className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-text-dim)]">
          v0.1.0 · local
        </span>
      </div>
      {!landscape && (
        <div className="flex items-center gap-3 font-mono text-[10px] uppercase tracking-widest text-[var(--color-text-muted)]">
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent-cyan)] animate-pulse-soft" />
            link
          </span>
          <span>tailnet</span>
          <span>tls</span>
        </div>
      )}
    </div>
  );
}

const MODE_COLOR = {
  IDLE: "var(--color-accent-cyan)",
  THINKING: "var(--color-accent-cyan)",
  BUILDING: "var(--color-accent-amber)",
  SEARCHING: "var(--color-accent-violet)",
};

/** Floating mode pill for Pi/landscape mode, since the full HUD is hidden. */
function CornerMode() {
  const mode = useDelphiStore((s) => s.mode);
  const color = MODE_COLOR[mode] ?? "var(--color-accent-cyan)";
  return (
    <div className="absolute right-3 top-3 z-20 flex items-center gap-2 rounded-sm border border-[var(--color-border-strong)] bg-[var(--color-bg-panel)]/80 px-2 py-1 backdrop-blur">
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: color, boxShadow: `0 0 6px ${color}` }}
      />
      <span
        className="font-display text-[10px] tracking-[0.3em]"
        style={{ color }}
      >
        {mode}
      </span>
    </div>
  );
}

export default App;
