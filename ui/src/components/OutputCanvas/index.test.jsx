import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { OutputCanvas } from "./index";
import { useChatStore } from "../../store/chatStore";
import { useDelphiStore } from "../../store/delphiStore";

/**
 * OutputCanvas — PreviewBlock 'media' branch.
 *
 * We seed the stores directly (the component is a read-only consumer) and
 * assert that the media preview renders the expected DOM. Code/document
 * branches are exercised indirectly via the existing useDelphiStream tests.
 */
beforeEach(() => {
  useChatStore.getState().clear();
  useDelphiStore.getState().reset();
});

describe("OutputCanvas preview toolbar", () => {
  it("renders DOWNLOAD and COPY buttons for a document preview", () => {
    useDelphiStore.getState().setPreview({
      kind: "document",
      content: "# Heading\n\nSome prose.",
    });
    render(<OutputCanvas />);
    expect(screen.getByLabelText("Download preview as a file")).toBeInTheDocument();
    expect(screen.getByLabelText("Copy preview to clipboard")).toBeInTheDocument();
  });

  it("renders DOWNLOAD and COPY buttons for a code preview", () => {
    useDelphiStore.getState().setPreview({
      kind: "code",
      language: "python",
      content: "print('hi')",
    });
    render(<OutputCanvas />);
    expect(screen.getByLabelText("Download preview as a file")).toBeInTheDocument();
    expect(screen.getByLabelText("Copy preview to clipboard")).toBeInTheDocument();
  });

  it("does NOT render the toolbar for a media preview (no body to download)", () => {
    useDelphiStore.getState().setPreview({
      kind: "media",
      url: "data:image/png;base64,AAA",
      alt: "ok",
      mimeType: "image/png",
    });
    render(<OutputCanvas />);
    expect(screen.queryByLabelText("Download preview as a file")).toBeNull();
    expect(screen.queryByLabelText("Copy preview to clipboard")).toBeNull();
  });
});

describe("OutputCanvas media preview", () => {
  it("renders an <img> with alt text when mimeType is an image/*", () => {
    useDelphiStore.getState().setPreview({
      kind: "media",
      url: "data:image/png;base64,AAA",
      alt: "user attachment",
      mimeType: "image/png",
    });

    render(<OutputCanvas />);

    const img = screen.getByAltText("user attachment");
    expect(img.tagName).toBe("IMG");
    expect(img.getAttribute("src")).toBe("data:image/png;base64,AAA");
    expect(screen.getByText("MEDIA ──")).toBeInTheDocument();
  });

  it("falls back to a 'media unavailable' pill for an unsupported mimeType", () => {
    useDelphiStore.getState().setPreview({
      kind: "media",
      url: "https://example.com/file.pdf",
      alt: "report",
      mimeType: "application/pdf",
    });

    render(<OutputCanvas />);

    expect(screen.queryByRole("img")).toBeNull();
    const pill = screen.getByLabelText("media unavailable");
    expect(pill.textContent).toMatch(/report/);
  });

  it("falls back to the pill when url is missing", () => {
    useDelphiStore.getState().setPreview({
      kind: "media",
      url: "",
      alt: "nothing",
      mimeType: "image/png",
    });
    render(<OutputCanvas />);
    expect(screen.getByLabelText("media unavailable")).toBeInTheDocument();
  });
});
