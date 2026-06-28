import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";

export const MyComposition = () => {
  const frame = useCurrentFrame(); // 0 → 89 (3s at 30fps)

  // Fade in the whole scene over the first 20 frames
  const opacity = interpolate(frame, [0, 20], [0, 1], { extrapolateRight: "clamp" });

  // Pancracio slides up from below: starts at y=80, settles at y=0 by frame 25
  const translateY = interpolate(frame, [0, 25], [80, 0], { extrapolateRight: "clamp" });

  // Title text fades in a bit later (frame 15–35)
  const titleOpacity = interpolate(frame, [15, 35], [0, 1], { extrapolateRight: "clamp" });

  // Subtitle appears last (frame 35–50)
  const subtitleOpacity = interpolate(frame, [35, 50], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: "#f5e6c8", justifyContent: "center", alignItems: "center", fontFamily: "sans-serif" }}>
      {/* Character image slides up and fades in */}
      <Img
        src={staticFile("pancracio.png")}
        style={{
          width: 320,
          height: 320,
          objectFit: "contain",
          opacity,
          transform: `translateY(${translateY}px)`,
          marginBottom: 24,
        }}
      />

      {/* Title */}
      <div style={{ opacity: titleOpacity, fontSize: 48, fontWeight: 800, color: "#3a2a1a", letterSpacing: 1 }}>
        Pancracio
      </div>

      {/* Subtitle */}
      <div style={{ opacity: subtitleOpacity, fontSize: 22, color: "#7a5c3a", marginTop: 8 }}>
        The AI Capybara
      </div>
    </AbsoluteFill>
  );
};
