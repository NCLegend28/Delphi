import { useEffect, useState } from "react";

/**
 * useViewport — bucket the current screen into a device tier.
 *
 * Tiers (used to pick a layout, not to style — fine-grain styling stays
 * Tailwind-driven):
 *
 *   tiny    width < 480  OR height < 320   (Pi HAT, smallest LCDs)
 *   phone   width < 640  AND height ≥ 320  (handset portrait)
 *   pi      width 640-960 AND height < 540 (Pi 7" landscape, car displays)
 *   laptop  width 960-1440                 (typical notebook)
 *   desktop width ≥ 1440                   (24" + monitor / wall)
 *
 * SSR-safe (returns 'laptop' before mount).
 */
export function useViewport() {
  const [tier, setTier] = useState("laptop");

  useEffect(() => {
    const compute = () => setTier(classify(window.innerWidth, window.innerHeight));
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, []);

  return tier;
}

function classify(w, h) {
  if (w < 480 || h < 320) return "tiny";
  if (w < 640) return "phone";
  if (w < 960 && h < 540) return "pi";
  if (w < 1440) return "laptop";
  return "desktop";
}
