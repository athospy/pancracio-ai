import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";

// ─── Segment data ────────────────────────────────────────────────────────────
// Durations come straight from the real generated Voicebox audio (ffprobe), not
// guessed — see internal-docs/video-production/guide-to-being-less-available.md
// for the full production log. Layout per segment (A/B/C) was decided from the
// vertical-layout mockup test in the same doc.
const FPS = 30;

type Layout = "A" | "B" | "C";

type SegmentDef = {
  id: number;
  layout: Layout;
  image: string;
  audio: string;
  seconds: number;
  caption: string;
};

const SEGMENT_DEFS: SegmentDef[] = [
  {
    id: 1,
    layout: "A",
    image: "seg1-background.png",
    audio: "seg1-cold-open.wav",
    seconds: 5.44,
    caption:
      "People think peace comes from finishing everything. It does not. Everything grows back.",
  },
  {
    id: 2,
    layout: "B",
    image: "seg2-background.png",
    audio: "seg2-demand-for-immediacy.wav",
    seconds: 14.32,
    caption:
      "The phone lights up again. A message. A ping. A little red circle. Each one arrives like it is the only thing that matters right now. As if waiting were dangerous. As if silence meant something was wrong.",
  },
  {
    id: 3,
    layout: "B",
    image: "seg3-background.png",
    audio: "seg3-someone-elses-urgency.wav",
    seconds: 17.36,
    caption:
      "But look closer. Most of what feels urgent… is not yours. It is someone else's deadline. Someone else's impatience. Someone else's bad planning, arriving in your pocket disguised as an emergency. Their urgency is real to them. That does not make it yours to carry.",
  },
  {
    id: 4,
    layout: "B",
    image: "seg4-background.png",
    audio: "seg4-guilt-of-not-replying.wav",
    seconds: 17.28,
    caption:
      "You feel it the moment you do not answer right away — that small guilty pull, like you have failed someone. But being reachable every second is not the same as being reliable. A reliable friend shows up when it counts. Reachable is a setting on your phone. Reliable is a decision you make.",
  },
  {
    id: 5,
    layout: "B",
    image: "seg5-background.png",
    audio: "seg5-what-silence-gives-you.wav",
    seconds: 15.68,
    caption:
      "So sometimes… he stops answering. Not out of anger. Not out of avoidance. Just to let the noise settle. In that quiet, the urgent things reveal what they really were… and the important things finally get room to be heard.",
  },
  {
    id: 6,
    layout: "C",
    image: "seg6-background.png",
    audio: "seg6-practical-boundaries.wav",
    seconds: 21.92,
    caption:
      "So here is the practical part. Not everything gets to interrupt you. Turn some notifications off. Not all — just the ones pretending to be emergencies. Decide who gets to reach you right away, and let everyone else wait for a moment you choose, not a moment they demand. Attention is not infinite. Spend it on what actually deserves it.",
  },
  {
    id: 7,
    layout: "A",
    image: "seg7-background.png",
    audio: "seg7-main-conclusion.wav",
    seconds: 10.8,
    caption:
      "He picks up the phone… and sets it face down. Not turned off. Not thrown away. Just… placed somewhere it cannot reach him first. That one choice changes the whole day.",
  },
  {
    id: 8,
    layout: "A",
    image: "seg8-background.png",
    audio: "seg8-closing-and-cta.wav",
    seconds: 7.6,
    caption:
      "You do not have to disappear. You only have to stop being available to everything. Choose your peace… on purpose.",
  },
];

const SEGMENTS = SEGMENT_DEFS.map((def) => ({
  ...def,
  durationInFrames: Math.ceil(def.seconds * FPS),
}));

export const TOTAL_DURATION_IN_FRAMES = SEGMENTS.reduce(
  (sum, s) => sum + s.durationInFrames,
  0
);

// ─── Captions ────────────────────────────────────────────────────────────────
// Splits each segment's script into sentences and spreads them proportionally
// (by character count) across the segment's REAL audio duration. This is a
// placeholder for true word-level sync (no forced-alignment/ASR pass has been
// run on this audio yet) — flagged as a known simplification in the production
// doc's open items, not hand-guessed frame numbers like the discarded CloseTabs
// composition used.
type CaptionCue = { text: string; start: number; end: number };

function buildCaptionSchedule(text: string, durationInFrames: number): CaptionCue[] {
  const sentences =
    text.match(/[^.!?]+[.!?]+/g)?.map((s) => s.trim()).filter(Boolean) ?? [text.trim()];
  const weights = sentences.map((s) => s.length);
  const totalWeight = weights.reduce((a, b) => a + b, 0);
  const gap = 4;
  const totalGap = gap * (sentences.length - 1);
  const usable = Math.max(durationInFrames - totalGap, sentences.length);

  let cursor = 0;
  return sentences.map((sentenceText, i) => {
    const frames = Math.max(Math.round((weights[i] / totalWeight) * usable), 1);
    const start = cursor;
    const end = Math.min(start + frames, durationInFrames);
    cursor = end + gap;
    return { text: sentenceText, start, end };
  });
}

const Captions: React.FC<{ schedule: CaptionCue[]; layout: Layout }> = ({
  schedule,
  layout,
}) => {
  const frame = useCurrentFrame();
  const active = schedule.find((c) => frame >= c.start && frame < c.end);
  if (!active) return null;

  const fade = interpolate(
    frame,
    [active.start, active.start + 6, active.end - 6, active.end],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  if (layout === "C") {
    // Text lives inside the dedicated dark card baked into the seg6 background.
    return (
      <div
        style={{
          position: "absolute",
          top: 1152,
          height: 768,
          left: 0,
          right: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 70px",
          opacity: fade,
        }}
      >
        <div
          style={{
            fontFamily: "Georgia, 'Times New Roman', serif",
            fontSize: 42,
            lineHeight: 1.4,
            textAlign: "center",
            color: "#f2ead9",
          }}
        >
          {active.text}
        </div>
      </div>
    );
  }

  // Layouts A and B: bottom-anchored semi-transparent caption bar.
  return (
    <div
      style={{
        position: "absolute",
        bottom: 140,
        left: 0,
        right: 0,
        display: "flex",
        justifyContent: "center",
        padding: "0 60px",
        opacity: fade,
      }}
    >
      <div
        style={{
          backgroundColor: "rgba(0,0,0,0.45)",
          borderRadius: 20,
          padding: "20px 40px",
          maxWidth: 880,
        }}
      >
        <div
          style={{
            fontFamily: "system-ui, -apple-system, sans-serif",
            fontWeight: 700,
            fontSize: 40,
            lineHeight: 1.3,
            textAlign: "center",
            color: "#fff",
          }}
        >
          {active.text}
        </div>
      </div>
    </div>
  );
};

// ─── Segment (background + Ken Burns + audio + captions) ───────────────────
const SegmentLayer: React.FC<{
  segment: (typeof SEGMENTS)[number];
  zoomIn: boolean;
}> = ({ segment, zoomIn }) => {
  const frame = useCurrentFrame();
  const schedule = buildCaptionSchedule(segment.caption, segment.durationInFrames);

  const scale = interpolate(
    frame,
    [0, segment.durationInFrames],
    zoomIn ? [1, 1.06] : [1.06, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      <Audio src={staticFile(`guide-to-being-less-available/audio/${segment.audio}`)} />
      <div style={{ width: "100%", height: "100%", transform: `scale(${scale})` }}>
        <Img
          src={staticFile(`guide-to-being-less-available/${segment.image}`)}
          style={{ width: "100%", height: "100%", objectFit: "cover" }}
        />
      </div>
      <Captions schedule={schedule} layout={segment.layout} />
    </AbsoluteFill>
  );
};

// ─── Main composition ────────────────────────────────────────────────────────
export const GuideToBeingLessAvailable: React.FC = () => {
  let cursor = 0;
  const sequences = SEGMENTS.map((segment, i) => {
    const from = cursor;
    cursor += segment.durationInFrames;
    return (
      <Sequence key={segment.id} from={from} durationInFrames={segment.durationInFrames}>
        <SegmentLayer segment={segment} zoomIn={i % 2 === 0} />
      </Sequence>
    );
  });

  return <AbsoluteFill style={{ backgroundColor: "#000" }}>{sequences}</AbsoluteFill>;
};
