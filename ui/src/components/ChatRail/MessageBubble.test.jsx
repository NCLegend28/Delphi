import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MessageBubble } from "./MessageBubble";

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
});
