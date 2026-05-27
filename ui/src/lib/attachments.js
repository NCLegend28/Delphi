/**
 * attachments.js — client-side image normalization for the chat draft.
 *
 * Resizes large images down to a sane longest-edge cap and re-encodes as JPEG
 * so we don't push 10MB iPhone photos through the data-URL chat path. Uses
 * OffscreenCanvas when available (Workers/modern browsers) and falls back to
 * a regular <canvas> + createImageBitmap.
 *
 * Pure utility — no React, no store, no network. Task 6 is what actually sends
 * the resulting data URL upstream.
 */

export const MAX_EDGE_PX = 1568;
export const JPEG_QUALITY = 0.85;
// Files smaller than this skip the re-encode path entirely.
export const SMALL_IMAGE_BYTES = 256 * 1024;

/**
 * Process a single image File.
 * @param {File} file
 * @returns {Promise<{mimeType:string,dataUrl:string,width:number,height:number,originalBytes:number,encodedBytes:number}>}
 */
export async function processImage(file) {
  if (!file || typeof file !== "object") {
    throw new Error("attachments: file is required");
  }
  const type = (file.type || "").toLowerCase();
  if (!type.startsWith("image/")) {
    throw new Error(`attachments: not an image (${type || "unknown"})`);
  }

  const originalBytes = file.size ?? 0;

  // Decode dimensions. createImageBitmap is the cheap path; if it's missing
  // (older Safari, jsdom test env) fall back to HTMLImageElement.
  const bitmap = await decodeBitmap(file);
  const { width: srcW, height: srcH } = bitmap;
  const { width, height, scaled } = fitToCap(srcW, srcH, MAX_EDGE_PX);

  // Tiny PNG/JPEGs that already fit can be passed through unchanged.
  if (!scaled && originalBytes > 0 && originalBytes <= SMALL_IMAGE_BYTES) {
    const dataUrl = await fileToDataUrl(file);
    closeBitmap(bitmap);
    return {
      mimeType: type,
      dataUrl,
      width: srcW,
      height: srcH,
      originalBytes,
      encodedBytes: dataUrl.length,
    };
  }

  const { blob, mimeType } = await renderToJpeg(bitmap, width, height);
  closeBitmap(bitmap);
  const dataUrl = await blobToDataUrl(blob);
  return {
    mimeType,
    dataUrl,
    width,
    height,
    originalBytes,
    encodedBytes: blob.size,
  };
}

export function fitToCap(w, h, cap = MAX_EDGE_PX) {
  if (!w || !h) return { width: w, height: h, scaled: false };
  const longest = Math.max(w, h);
  if (longest <= cap) return { width: w, height: h, scaled: false };
  const k = cap / longest;
  return {
    width: Math.round(w * k),
    height: Math.round(h * k),
    scaled: true,
  };
}

async function decodeBitmap(file) {
  if (typeof createImageBitmap === "function") {
    try {
      return await createImageBitmap(file);
    } catch {
      // Fall through to <img> path.
    }
  }
  return decodeViaImageElement(file);
}

function decodeViaImageElement(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve({
        width: img.naturalWidth || img.width,
        height: img.naturalHeight || img.height,
        _img: img,
      });
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("attachments: failed to decode image"));
    };
    img.src = url;
  });
}

function closeBitmap(bitmap) {
  if (bitmap && typeof bitmap.close === "function") bitmap.close();
}

async function renderToJpeg(source, width, height) {
  const mimeType = "image/jpeg";
  if (typeof OffscreenCanvas !== "undefined") {
    try {
      const canvas = new OffscreenCanvas(width, height);
      const ctx = canvas.getContext("2d");
      ctx.drawImage(sourceFor(source), 0, 0, width, height);
      const blob = await canvas.convertToBlob({ type: mimeType, quality: JPEG_QUALITY });
      return { blob, mimeType };
    } catch {
      // Fall through to DOM canvas.
    }
  }
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(sourceFor(source), 0, 0, width, height);
  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("attachments: toBlob failed"))),
      mimeType,
      JPEG_QUALITY,
    );
  });
  return { blob, mimeType };
}

function sourceFor(decoded) {
  // decodeViaImageElement returns an object wrapping HTMLImageElement; the
  // bitmap path returns the bitmap itself — both are valid drawImage sources.
  return decoded._img ?? decoded;
}

function fileToDataUrl(file) {
  return blobToDataUrl(file);
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error ?? new Error("attachments: FileReader failed"));
    reader.readAsDataURL(blob);
  });
}
