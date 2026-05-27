import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Footer } from "./index";
import { useDelphiStore } from "../../store/delphiStore";

const initialState = useDelphiStore.getState();

beforeEach(() => {
  // Fresh fake speechSynthesis so the toggle isn't disabled by default.
  window.speechSynthesis = { cancel: () => {}, speak: () => {}, speaking: false };
  window.SpeechSynthesisUtterance = function (t) { this.text = t; };
  window.localStorage.clear();
  useDelphiStore.setState({ ...initialState, autoSpeakEnabled: false });
});

afterEach(() => {
  delete window.speechSynthesis;
  delete window.SpeechSynthesisUtterance;
});

describe("Footer AUTO-SPEAK toggle", () => {
  it("renders OFF by default", () => {
    render(<Footer />);
    const btn = screen.getByRole("button", { name: /AUTO-SPEAK/i });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    expect(btn.textContent).toMatch(/OFF/);
  });

  it("clicking toggles store + persists to localStorage", () => {
    render(<Footer />);
    const btn = screen.getByRole("button", { name: /AUTO-SPEAK/i });
    fireEvent.click(btn);
    expect(useDelphiStore.getState().autoSpeakEnabled).toBe(true);
    expect(btn).toHaveAttribute("aria-pressed", "true");
    expect(btn.textContent).toMatch(/ON/);
    expect(window.localStorage.getItem("delphi:autoSpeak")).toBe("1");
    fireEvent.click(btn);
    expect(useDelphiStore.getState().autoSpeakEnabled).toBe(false);
    expect(window.localStorage.getItem("delphi:autoSpeak")).toBe("0");
  });

  it("disabled when speech synthesis is unsupported", () => {
    delete window.speechSynthesis;
    render(<Footer />);
    const btn = screen.getByRole("button", { name: /AUTO-SPEAK/i });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(useDelphiStore.getState().autoSpeakEnabled).toBe(false);
  });
});
