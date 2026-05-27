import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MessageBubble } from "./MessageBubble";

beforeEach(() => {
  window.speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn(),
    speaking: false,
  };
  window.SpeechSynthesisUtterance = function (t) {
    this.text = t;
  };
});

afterEach(() => {
  delete window.speechSynthesis;
  delete window.SpeechSynthesisUtterance;
});

describe("MessageBubble", () => {
  it("renders plain user text", () => {
    render(<MessageBubble role="user" content="hello there" />);
    expect(screen.getByText("hello there")).toBeInTheDocument();
    expect(screen.getByText("YOU")).toBeInTheDocument();
  });

  it("renders image thumbnails for user attachments", () => {
    render(
      <MessageBubble
        role="user"
        content="what's this?"
        attachments={[
          {
            id: "a1",
            kind: "image",
            dataUrl: "data:image/jpeg;base64,xxxx",
            mimeType: "image/jpeg",
            width: 100,
            height: 100,
          },
          {
            id: "a2",
            kind: "image",
            dataUrl: "data:image/jpeg;base64,yyyy",
            mimeType: "image/jpeg",
            width: 50,
            height: 50,
          },
        ]}
      />,
    );
    const strip = screen.getByTestId("bubble-thumbs");
    expect(strip.querySelectorAll("img")).toHaveLength(2);
  });

  it("shows transcript badge for audio-origin messages", () => {
    render(
      <MessageBubble
        role="user"
        content=""
        transcript="hello from voice"
        audioUrl="blob:abc"
      />,
    );
    expect(screen.getByText(/TRANSCRIPT/)).toBeInTheDocument();
    expect(screen.getByText("hello from voice")).toBeInTheDocument();
  });

  it("does not render attachments for assistant", () => {
    render(
      <MessageBubble
        role="assistant"
        content="ok"
        attachments={[{ id: "x", kind: "image", dataUrl: "data:image/png;base64,z" }]}
      />,
    );
    expect(screen.queryByTestId("bubble-thumbs")).not.toBeInTheDocument();
  });

  it("shows SPEAK button for non-streaming assistant bubble with text", () => {
    render(<MessageBubble role="assistant" content="hello operator" />);
    const btn = screen.getByRole("button", { name: /speak response/i });
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(window.speechSynthesis.speak).toHaveBeenCalledTimes(1);
  });

  it("does not show SPEAK while assistant bubble is streaming", () => {
    render(<MessageBubble role="assistant" content="partial..." streaming />);
    expect(screen.queryByRole("button", { name: /speak response/i })).toBeNull();
  });

  it("does not show SPEAK on user bubbles", () => {
    render(<MessageBubble role="user" content="hi" />);
    expect(screen.queryByRole("button", { name: /speak response/i })).toBeNull();
  });
});
