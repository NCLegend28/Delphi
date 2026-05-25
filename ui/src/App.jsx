import { useEffect } from "react";
import { Header } from "./components/Header";
import { Footer } from "./components/Footer";
import { Sidebar } from "./components/Sidebar";
import { OutputCanvas } from "./components/OutputCanvas";
import { ChatRail } from "./components/ChatRail";
import { CompactBar } from "./components/CompactBar";
import { BootOverlay } from "./components/BootOverlay";
import { useViewport } from "./hooks/useViewport";
import { useChatStore } from "./store/chatStore";
import { useDelphiStore } from "./store/delphiStore";
import { cancelDelphiStream } from "./hooks/useDelphiStream";

/**
 * App — adaptive mission-control shell.
 *
 * One component tree, three layout modes keyed off the viewport tier:
 *
 *   tiny / phone   → compact: CompactBar strip + ChatRail
 *   pi             → landscape: Header + OutputCanvas over ChatRail (no sidebar)
 *   laptop/desktop → full: header / (canvas+chat | sidebar) / footer grid
 *
 * Global shortcuts (full/landscape and compact alike):
 *   ⌘K / Ctrl+K  focus the prompt
 *   ⌘L / Ctrl+L  clear the session
 *   Esc          interrupt the in-flight stream
 */
function App() {
  const tier = useViewport();
  const compact = tier === "tiny" || tier === "phone";
  const landscape = tier === "pi";

  useKeyboardShortcuts();

  return (
    <>
      <BootOverlay />
      {compact ? (
        <div className="grid h-full w-full grid-rows-[auto_1fr] gap-1 p-1">
          <CompactBar />
          <div className="min-h-0">
            <ChatRail />
          </div>
        </div>
      ) : landscape ? (
        <div className="grid h-full w-full grid-rows-[34px_1fr_36px] gap-px bg-[var(--color-border-dim)] p-px">
          <Header />
          <div className="grid min-h-0 grid-rows-[1fr_150px] gap-px">
            <OutputCanvas />
            <ChatRail />
          </div>
          <Footer />
        </div>
      ) : (
        <div
          className="grid h-full w-full gap-px bg-[var(--color-border-dim)] p-px"
          style={{
            gridTemplateRows: "38px 1fr 42px",
            gridTemplateColumns: "1fr 280px",
            gridTemplateAreas: '"header header" "main sidebar" "footer footer"',
          }}
        >
          <div style={{ gridArea: "header" }}>
            <Header />
          </div>
          <main className="grid min-h-0 grid-rows-[1fr_190px] gap-px" style={{ gridArea: "main" }}>
            <OutputCanvas />
            <ChatRail />
          </main>
          <div className="min-h-0" style={{ gridArea: "sidebar" }}>
            <Sidebar />
          </div>
          <div style={{ gridArea: "footer" }}>
            <Footer />
          </div>
        </div>
      )}
    </>
  );
}

function useKeyboardShortcuts() {
  useEffect(() => {
    const onKey = (e) => {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === "k") {
        e.preventDefault();
        window.dispatchEvent(new Event("delphi:focus-input"));
      } else if (meta && e.key.toLowerCase() === "l") {
        e.preventDefault();
        clearSession();
      } else if (e.key === "Escape" && useChatStore.getState().isStreaming) {
        cancelDelphiStream();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

function clearSession() {
  useChatStore.getState().clear();
  const delphi = useDelphiStore.getState();
  delphi.reset();
  delphi.pushEvent("Session cleared by operator");
}

export default App;
