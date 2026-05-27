import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useRecorder } from "./useRecorder";

class FakeMediaRecorder {
  static isTypeSupported() {
    return true;
  }
  constructor(stream, opts) {
    this.stream = stream;
    this.mimeType = opts?.mimeType ?? "audio/webm";
    this.state = "inactive";
    this.ondataavailable = null;
    this.onstop = null;
    this.onerror = null;
    FakeMediaRecorder.last = this;
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["abc"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

beforeEach(() => {
  window.MediaRecorder = FakeMediaRecorder;
  window.navigator.mediaDevices = {
    getUserMedia: vi.fn(async () => ({
      getTracks: () => [{ stop: vi.fn() }],
    })),
  };
  globalThis.URL.createObjectURL = vi.fn(() => "blob:fake");
  globalThis.URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useRecorder", () => {
  it("reports support", () => {
    const { result } = renderHook(() => useRecorder());
    expect(result.current.supported).toBe(true);
    expect(result.current.status).toBe("idle");
  });

  it("transitions idle → recording → stopped", async () => {
    const { result } = renderHook(() => useRecorder());
    await act(async () => {
      await result.current.start();
    });
    expect(result.current.status).toBe("recording");

    act(() => {
      result.current.stop();
    });

    await waitFor(() => expect(result.current.status).toBe("stopped"));
    expect(result.current.blob).toBeInstanceOf(Blob);
    expect(result.current.blobUrl).toBe("blob:fake");
    expect(result.current.mimeType).toContain("audio/");
  });

  it("handles permission denial gracefully", async () => {
    window.navigator.mediaDevices.getUserMedia = vi.fn(async () => {
      const err = new Error("denied");
      err.name = "NotAllowedError";
      throw err;
    });
    const { result } = renderHook(() => useRecorder());
    await act(async () => {
      await result.current.start();
    });
    expect(result.current.status).toBe("denied");
    expect(result.current.error).toBeInstanceOf(Error);
  });

  it("cancel resets state and revokes blob url", async () => {
    const { result } = renderHook(() => useRecorder());
    await act(async () => {
      await result.current.start();
    });
    act(() => result.current.stop());
    await waitFor(() => expect(result.current.status).toBe("stopped"));

    act(() => result.current.cancel());
    expect(result.current.status).toBe("idle");
    expect(result.current.blob).toBeNull();
    expect(result.current.blobUrl).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:fake");
  });
});
