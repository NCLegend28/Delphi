import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { InputBar } from "./InputBar";

// Stub out chatStore — InputBar only reads `isStreaming`.
vi.mock("../../store/chatStore", () => ({
  useChatStore: (selector) => selector({ isStreaming: false }),
}));

// Stub processImage so we can fire file-input changes without a real canvas.
vi.mock("../../lib/attachments", () => ({
  processImage: vi.fn(async (file) => ({
    mimeType: file.type,
    dataUrl: "data:image/jpeg;base64,fake",
    width: 100,
    height: 100,
    originalBytes: file.size,
    encodedBytes: 12,
  })),
}));

function fakeRecorder(overrides = {}) {
  return () => ({
    supported: true,
    status: "idle",
    start: vi.fn(),
    stop: vi.fn(),
    cancel: vi.fn(),
    blob: null,
    blobUrl: null,
    mimeType: "",
    durationMs: 0,
    error: null,
    ...overrides,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("InputBar", () => {
  it("submits plain text via onSubmit", () => {
    const onSubmit = vi.fn();
    render(<InputBar onSubmit={onSubmit} recorderHook={fakeRecorder()} />);
    const ta = screen.getByPlaceholderText(/message delphi/i);
    fireEvent.change(ta, { target: { value: "hi" } });
    fireEvent.keyDown(ta, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0]).toBe("hi");
    expect(onSubmit.mock.calls[0][1]).toMatchObject({
      text: "hi",
      images: [],
      audio: null,
    });
  });

  it("adds a thumbnail after picking an image, then removes it", async () => {
    const onSubmit = vi.fn();
    render(<InputBar onSubmit={onSubmit} recorderHook={fakeRecorder()} />);
    const fileInput = screen.getByTestId("file-input");
    const file = new File([new Uint8Array(8)], "a.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(screen.getAllByTestId("thumb")).toHaveLength(1));

    const removeBtn = screen.getByRole("button", { name: /remove attachment/i });
    fireEvent.click(removeBtn);
    expect(screen.queryByTestId("thumb")).not.toBeInTheDocument();
  });

  it("renders mic stop control when recording", () => {
    const onSubmit = vi.fn();
    render(
      <InputBar
        onSubmit={onSubmit}
        recorderHook={fakeRecorder({ status: "recording" })}
      />,
    );
    const mic = screen.getByTestId("mic-button");
    expect(mic).toHaveAccessibleName(/stop recording/i);
  });

  it("renders audio preview when a clip is captured", () => {
    const onSubmit = vi.fn();
    render(
      <InputBar
        onSubmit={onSubmit}
        recorderHook={fakeRecorder({
          status: "stopped",
          blob: new Blob(["x"], { type: "audio/webm" }),
          blobUrl: "blob:audio",
          mimeType: "audio/webm",
          durationMs: 4200,
        })}
      />,
    );
    expect(screen.getByTestId("audio-preview")).toBeInTheDocument();
  });
});
