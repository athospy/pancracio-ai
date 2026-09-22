import React from "react";
import { AbsoluteFill, Img, staticFile, continueRender, delayRender } from "remotion";

/**
 * Static quote-card composition for the daily Instagram image posts.
 *
 * Why this exists: GPT-4o renders text as pixels that merely look like letters, so
 * asking it for the character AND the typography in one pass produced mangled words and
 * a layout that changed on every regeneration. The split is — GPT-4o generates a
 * text-free background plate (Pancracio + props, empty wall on the left), and this
 * composition lays the type over it. Text is then correct by construction and identical
 * across every post in a batch.
 *
 * See internal-docs/pipeline/chatgpt-image-post-prompt.md for the plate prompt.
 */

export const POST_WIDTH = 1122;
export const POST_HEIGHT = 1402;

/** Palette sampled from the published Jun 2026 batch. */
const INK = "#4A2E1A";
const RULE = "rgba(122, 84, 52, 0.45)";

export type PancracioQuoteProps = {
  /** Path inside remotion/public/, e.g. "image-posts/post-01-want-the-prize.png" */
  backgroundSrc: string;
  /**
   * Quote broken into lines by hand — line breaks are a design decision, not wrapping.
   * An empty string renders a half-line gap, for separating two sentences.
   */
  quoteLines: string[];
  headerText: string;
  attribution: string;
  /** Quote size in px. Drop it for longer quotes so the block still clears the character. */
  quoteFontSize: number;
  /** Left edge of the text column, and how wide it may run. */
  textLeft: number;
  textWidth: number;
  /** Top of the header block. */
  textTop: number;
};

export const defaultPancracioQuoteProps: PancracioQuoteProps = {
  backgroundSrc: "image-posts/post-01-want-the-prize.png",
  quoteLines: ["Before asking", "how to win,", "ask if you", "want the prize."],
  headerText: "Tiny advice from a serious capybara:",
  attribution: "— pancracio.capy",
  quoteFontSize: 76,
  textLeft: 78,
  textWidth: 470,
  textTop: 132,
};

/**
 * Fonts are served from public/fonts rather than the Google Fonts CDN so a render never
 * depends on the network. delayRender holds the frame until the faces are ready —
 * without it the still can rasterise in a fallback serif.
 */
const useLocalFonts = () => {
  const [handle] = React.useState(() => delayRender("Loading Playfair Display"));

  React.useEffect(() => {
    const faces = [
      new FontFace(
        "Playfair Display",
        `url(${staticFile("fonts/PlayfairDisplay-400.woff2")}) format('woff2')`,
        { weight: "400", style: "normal" },
      ),
      new FontFace(
        "Playfair Display",
        `url(${staticFile("fonts/PlayfairDisplay-600.woff2")}) format('woff2')`,
        { weight: "600", style: "normal" },
      ),
      new FontFace(
        "Playfair Display",
        `url(${staticFile("fonts/PlayfairDisplay-400-italic.woff2")}) format('woff2')`,
        { weight: "400", style: "italic" },
      ),
    ];

    Promise.all(
      faces.map((face) => face.load().then((loaded) => document.fonts.add(loaded))),
    )
      .then(() => continueRender(handle))
      .catch(() => continueRender(handle));
  }, [handle]);
};

/** Lotus mark and hairlines that sit between the header and the quote. */
const Divider: React.FC = () => (
  <div style={{ display: "flex", alignItems: "center", gap: 16, margin: "20px 0 34px" }}>
    <div style={{ flex: 1, height: 1, background: RULE }} />
    <svg width="44" height="26" viewBox="0 0 44 26" fill="none">
      {/* upright centre petal */}
      <path
        d="M22 3c2.6 3.5 3.9 7 3.9 10.4 0 3-1 5.8-2.9 8.3h-2c-1.9-2.5-2.9-5.3-2.9-8.3C18.1 10 19.4 6.5 22 3z"
        stroke={INK}
        strokeWidth="1.2"
        fill="none"
      />
      {/* inner pair, leaning out */}
      <path
        d="M22 21.7c-1.6-4.1-4.4-7-8.4-8.6-1 4 .1 7.4 3.3 10.2 1.5 1.3 3.2 1.1 5.1-1.6z"
        stroke={INK}
        strokeWidth="1.2"
        fill="none"
      />
      <path
        d="M22 21.7c1.6-4.1 4.4-7 8.4-8.6 1 4-.1 7.4-3.3 10.2-1.5 1.3-3.2 1.1-5.1-1.6z"
        stroke={INK}
        strokeWidth="1.2"
        fill="none"
      />
      {/* outer pair, nearly horizontal */}
      <path
        d="M22 22.4c-3.2-2.9-7-4.1-11.4-3.6-2.9.3-5.4 1.4-7.6 3.2 3.1 2.2 6.6 3.2 10.4 2.9 3.3-.2 6.1-1.1 8.6-2.5z"
        stroke={INK}
        strokeWidth="1.2"
        fill="none"
      />
      <path
        d="M22 22.4c3.2-2.9 7-4.1 11.4-3.6 2.9.3 5.4 1.4 7.6 3.2-3.1 2.2-6.6 3.2-10.4 2.9-3.3-.2-6.1-1.1-8.6-2.5z"
        stroke={INK}
        strokeWidth="1.2"
        fill="none"
      />
    </svg>
    <div style={{ flex: 1, height: 1, background: RULE }} />
  </div>
);

export const PancracioQuote: React.FC<PancracioQuoteProps> = ({
  backgroundSrc,
  quoteLines,
  headerText,
  attribution,
  quoteFontSize,
  textLeft,
  textWidth,
  textTop,
}) => {
  useLocalFonts();

  return (
    <AbsoluteFill style={{ backgroundColor: "#E8DCC8" }}>
      <Img
        src={staticFile(backgroundSrc)}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />

      <AbsoluteFill
        style={{
          fontFamily: "'Playfair Display', Georgia, serif",
          color: INK,
        }}
      >
        <div
          style={{
            position: "absolute",
            left: textLeft,
            top: textTop,
            width: textWidth,
          }}
        >
          <div
            style={{
              fontSize: 26,
              fontWeight: 400,
              lineHeight: 1.35,
              letterSpacing: 0.2,
            }}
          >
            {headerText}
          </div>

          <Divider />

          <div
            style={{
              fontSize: quoteFontSize,
              fontWeight: 600,
              lineHeight: 1.12,
              letterSpacing: -0.5,
            }}
          >
            {quoteLines.map((line, i) =>
              line === "" ? (
                <div key={i} style={{ height: "0.5em" }} />
              ) : (
                <div key={i}>{line}</div>
              ),
            )}
          </div>

          <div
            style={{
              marginTop: 38,
              fontSize: 27,
              fontWeight: 400,
              fontStyle: "italic",
              letterSpacing: 0.3,
            }}
          >
            {attribution}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
