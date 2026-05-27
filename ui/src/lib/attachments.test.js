import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  fitToCap,
  MAX_EDGE_PX,
  JPEG_QUALITY,
  SMALL_IMAGE_BYTES,
  processImage,
} from "./attachments";

// Patch out the canvas/bitmap pipeline so we can exercise processImage in
// jsdom without a real GPU path. We feed processImage a fake File and stub
// createImageBitmap + canvas APIs to assert downstream behavior.
function installFakeImageDecoder({ width, height }) {
  globalThis.createImageBitmap = vi.fn(async () => ({
    width,
    height,
    close: vi.fn(),
  }));
}

function installFakeCanvas() {
  const drawImage = vi.fn();
  // toBlob path
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({ drawImage }));
  HTMLCanvasElement.prototype.toBlob = function (cb, type) {
    cb(new Blob(["jpeg-bytes"], { type: type ?? "image/jpeg" }));
  };
  return { drawImage };
}

function fakeFile({ type = "image/png", size = 1024, name = "x.png" } = {}) {
  const blob = new Blob([new Uint8Array(size)], { type });
  // jsdom Blob has no name property — give it one for File-ness.
  Object.defineProperty(blob, "name", { value: name });
  return blob;
}

beforeEach(() => {
  // Wipe OffscreenCanvas so we deterministically hit the DOM canvas branch.
  // eslint-disable-next-line no-undef
  delete globalThis.OffscreenCanvas;
  installFakeCanvas();
});

describe("attachments constants", () => {
  it("exports tunables", () => {
    expect(MAX_EDGE_PX).toBe(1568);
    expect(JPEG_QUALITY).toBeCloseTo(0.85);
    expect(SMALL_IMAGE_BYTES).toBeGreaterThan(0);
  });
});

describe("fitToCap", () => {
  it("leaves small images alone", () => {
    expect(fitToCap(640, 480)).toEqual({ width: 640, height: 480, scaled: false });
  });

  it("downscales landscape images preserving aspect", () => {
    const out = fitToCap(4000, 2000, 1000);
    expect(out.scaled).toBe(true);
    expect(out.width).toBe(1000);
    expect(out.height).toBe(500);
  });

  it("downscales portrait images preserving aspect", () => {
    const out = fitToCap(800, 3200, 1600);
    expect(out.scaled).toBe(true);
    expect(out.height).toBe(1600);
    expect(out.width).toBe(400);
  });
});

describe("processImage", () => {
  it("rejects non-image files", async () => {
    const txt = new Blob(["hi"], { type: "text/plain" });
    await expect(processImage(txt)).rejects.toThrow(/not an image/i);
  });

  it("rejects missing file", async () => {
    await expect(processImage(null)).rejects.toThrow();
  });

  it("passes small images through without re-encoding", async () => {
    installFakeImageDecoder({ width: 400, height: 300 });
    const file = fakeFile({ type: "image/png", size: 1024 });
    const out = await processImage(file);
    expect(out.mimeType).toBe("image/png");
    expect(out.width).toBe(400);
    expect(out.height).toBe(300);
    expect(out.dataUrl).toMatch(/^data:image\/png;/);
  });

  it("downscales and re-encodes large images to JPEG", async () => {
    installFakeImageDecoder({ width: 4000, height: 2000 });
    const file = fakeFile({ type: "image/png", size: SMALL_IMAGE_BYTES + 1 });
    const out = await processImage(file);
    expect(out.mimeType).toBe("image/jpeg");
    expect(Math.max(out.width, out.height)).toBe(MAX_EDGE_PX);
    expect(out.dataUrl).toMatch(/^data:image\/jpeg;/);
    expect(out.originalBytes).toBe(file.size);
    expect(out.encodedBytes).toBeGreaterThan(0);
  });
});
