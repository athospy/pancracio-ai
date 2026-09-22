import {
  AbsoluteFill,
  // Audio,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// ─── Tab data ───────────────────────────────────────────────────────────────
const TABS = [
  { label: "Emails I Owe Replies To",  emoji: "📧", color: "#FFE8E8", enterFrame: 0,  closeFrame: 180 },
  { label: "Thoughts From 3 AM",        emoji: "🌙", color: "#E8F0FF", enterFrame: 10, closeFrame: 240 },
  { label: "That Awkward Thing I Said", emoji: "😬", color: "#FFFBE8", enterFrame: 20, closeFrame: 300 },
  { label: "Plans I'll Start Monday",   emoji: "📋", color: "#E8FFE8", enterFrame: 30, closeFrame: 450 },
  { label: "Conversations I Replayed",  emoji: "💭", color: "#F0E8FF", enterFrame: 40, closeFrame: 455 },
];

const TAB_W = 300;
const TAB_H = 56;
const TAB_GAP = 20;

// Row 1: 3 tabs centered → x = 70, 390, 710
// Row 2: 2 tabs centered → x = 220, 540
const ROW1_X = (1080 - 3 * TAB_W - 2 * TAB_GAP) / 2;
const ROW2_X = (1080 - 2 * TAB_W - TAB_GAP) / 2;

const TAB_POSITIONS = [
  { x: ROW1_X,                              y: 60  },
  { x: ROW1_X + TAB_W + TAB_GAP,            y: 60  },
  { x: ROW1_X + 2 * (TAB_W + TAB_GAP),     y: 60  },
  { x: ROW2_X,                              y: 130 },
  { x: ROW2_X + TAB_W + TAB_GAP,            y: 130 },
];

// ─── Caption data ────────────────────────────────────────────────────────────
type Word = { text: string; frame: number };
type Sentence = { words: Word[]; startFrame: number; endFrame: number };

function buildSentence(text: string, startFrame: number, endFrame: number, wordInterval: number): Sentence {
  return {
    words: text.split(" ").map((word, i) => ({ text: word, frame: startFrame + i * wordInterval })),
    startFrame,
    endFrame,
  };
}

// Sentences timed to match the narration (3s–14s)
const SENTENCES: Sentence[] = [
  buildSentence("Your mind was not built to keep every tab open.", 90,  195, 9),  // 3s–6.5s, 10 words
  buildSentence("Some thoughts can be saved for later.",           210, 263, 6),  // 7s–8.8s, 7 words
  buildSentence("Some can be closed completely.",                  270, 337, 10), // 9s–11.2s, 5 words
  buildSentence("Peace begins when you stop refreshing everything.", 345, 445, 9), // 11.5s–14.9s, 7 words
];

// Paraguay flag colors for the outro underline
const STRIPE_COLORS = ["#D62828", "#FFFFFF", "#003087"];
const STRIPE_START = 510; // 17s

// ─── BrowserTab ──────────────────────────────────────────────────────────────
const BrowserTab: React.FC<{
  label: string;
  emoji: string;
  color: string;
  enterFrame: number;
  closeFrame: number;
  x: number;
  y: number;
}> = ({ label, emoji, color, enterFrame, closeFrame, x, y }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterProgress = spring({
    fps,
    frame: frame - enterFrame,
    config: { damping: 14, mass: 0.7, stiffness: 120 },
  });

  const enterY = interpolate(enterProgress, [0, 1], [-100, 0]);
  const enterOpacity = Math.min(1, enterProgress * 3);

  const closeProgress =
    frame >= closeFrame
      ? interpolate(frame, [closeFrame, closeFrame + 14], [0, 1], { extrapolateRight: "clamp" })
      : 0;

  // Stop rendering after exit animation
  if (frame >= closeFrame + 16) return null;

  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: TAB_W,
        height: TAB_H,
        backgroundColor: color,
        borderRadius: 14,
        display: "flex",
        alignItems: "center",
        paddingLeft: 16,
        paddingRight: 14,
        gap: 10,
        opacity: enterOpacity * interpolate(closeProgress, [0, 1], [1, 0]),
        transform: `translateY(${enterY}px) scale(${interpolate(closeProgress, [0, 1], [1, 0.5])})`,
        transformOrigin: "top center",
        boxShadow: "0 3px 12px rgba(0,0,0,0.10)",
      }}
    >
      <span style={{ fontSize: 22, flexShrink: 0 }}>{emoji}</span>
      <span
        style={{
          fontSize: 17,
          fontWeight: 600,
          color: "#2d1f0e",
          flex: 1,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 20, color: "#999", fontWeight: 300, flexShrink: 0 }}>×</span>
    </div>
  );
};

// ─── Captions ────────────────────────────────────────────────────────────────
const Captions: React.FC = () => {
  const frame = useCurrentFrame();
  const active = SENTENCES.find((s) => frame >= s.startFrame && frame <= s.endFrame);
  if (!active) return null;

  const fade = interpolate(
    frame,
    [active.startFrame, active.startFrame + 6, active.endFrame - 8, active.endFrame],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <div
      style={{
        backgroundColor: "rgba(0,0,0,0.45)",
        borderRadius: 18,
        padding: "18px 36px",
        opacity: fade,
        display: "flex",
        flexWrap: "wrap",
        justifyContent: "center",
        gap: 12,
        maxWidth: 900,
      }}
    >
      {active.words.map(({ text, frame: wf }, i) => {
        const wordOpacity = interpolate(frame, [wf, wf + 5], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        return (
          <span
            key={i}
            style={{
              opacity: wordOpacity,
              fontSize: 56,
              fontWeight: 800,
              color: "#fff",
              lineHeight: 1.2,
            }}
          >
            {text}
          </span>
        );
      })}
    </div>
  );
};

// ─── Outro stripes (17s–20s) ─────────────────────────────────────────────────
const OutroStripes: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        position: "absolute",
        bottom: 150,
        left: 0,
        right: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 8,
      }}
    >
      {STRIPE_COLORS.map((color, i) => {
        const start = STRIPE_START + i * 10;
        const width = interpolate(frame, [start, start + 35], [0, 860], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const opacity = interpolate(frame, [start + 55, 590], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        return (
          <div
            key={i}
            style={{
              width,
              height: 14,
              backgroundColor: color,
              borderRadius: 7,
              opacity,
            }}
          />
        );
      })}
    </div>
  );
};

// ─── Main composition ─────────────────────────────────────────────────────────
export const CloseTabs: React.FC = () => {
  const frame = useCurrentFrame();

  // Pancracio fades in at 2s (frame 60)
  const pancracioOpacity = interpolate(frame, [60, 85], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const pancracioScale = interpolate(frame, [60, 85], [0.88, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // CTA: fades in at 15s, fades out at 19s
  const ctaOpacity = interpolate(frame, [450, 475, 570, 595], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{ backgroundColor: "#FDF6EC", fontFamily: "system-ui, -apple-system, sans-serif" }}
    >
      {/* Optional: uncomment when voice.mp3 is placed in remotion/public/ */}
      {/* <Audio src={staticFile("voice.mp3")} /> */}

      {/* Pancracio — rendered first so tabs draw on top of it */}
      <div
        style={{
          position: "absolute",
          left: "50%",
          top: 170,
          transform: `translateX(-50%) scale(${pancracioScale})`,
          opacity: pancracioOpacity,
        }}
      >
        <Img
          src={staticFile("pancracio.png")}
          style={{ width: 580, height: 580, objectFit: "contain" }}
        />
      </div>

      {/* Browser tabs — drawn on top of Pancracio */}
      {TABS.map((tab, i) => (
        <BrowserTab
          key={i}
          label={tab.label}
          emoji={tab.emoji}
          color={tab.color}
          enterFrame={tab.enterFrame}
          closeFrame={tab.closeFrame}
          x={TAB_POSITIONS[i].x}
          y={TAB_POSITIONS[i].y}
        />
      ))}

      {/* Captions (3s–14.8s) */}
      <div
        style={{
          position: "absolute",
          bottom: 200,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          paddingLeft: 60,
          paddingRight: 60,
        }}
      >
        <Captions />
      </div>

      {/* CTA: "Close one tab today." (15s–19.8s) */}
      <div
        style={{
          position: "absolute",
          top: 900,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          opacity: ctaOpacity,
        }}
      >
        <div
          style={{
            fontSize: 72,
            fontWeight: 900,
            color: "#2d1f0e",
            textAlign: "center",
            padding: "0 80px",
            lineHeight: 1.25,
          }}
        >
          Close one tab today.
        </div>
      </div>

      {/* Outro: Paraguay scarf stripes (17s–20s) */}
      {frame >= STRIPE_START && <OutroStripes />}
    </AbsoluteFill>
  );
};
