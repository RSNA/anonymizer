import type React from "react";
import {
  AbsoluteFill,
  Img,
  Interactive,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  type InteractivitySchema,
} from "remotion";
import { COLORS, FONT } from "../theme";

type OpeningSceneProps = {
  readonly title: string;
  readonly subtitle: string;
  readonly style?: React.CSSProperties;
};

const OpeningSceneInner: React.FC<OpeningSceneProps> = ({
  title,
  subtitle,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        fontFamily: FONT,
        color: COLORS.text,
        justifyContent: "center",
        padding: "0 120px",
        ...style,
      }}
    >
      <Img
        name="RSNALogo"
        premountFor={fps}
        src={staticFile("rsna_logo.png")}
        style={{
          position: "absolute",
          top: 56,
          right: 72,
          width: 441,
          height: "auto",
          opacity: interpolate(frame, [0, 0.45 * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          translate: `0 ${interpolate(frame, [0, 0.45 * fps], [16, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })}px`,
        }}
      />
      <Img
        name="OpeningGraphic"
        premountFor={fps}
        src={staticFile("opening-graphic.jpg")}
        style={{
          position: "absolute",
          right: 72,
          bottom: 56,
          width: 460,
          height: "auto",
          borderRadius: 28,
          opacity: interpolate(frame, [0.35 * fps, 0.9 * fps], [0, 0.92], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          translate: `0 ${interpolate(frame, [0.35 * fps, 0.9 * fps], [20, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })}px`,
        }}
      />
      <Interactive.Div
        name="Badge"
        premountFor={fps}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 12,
          padding: "12px 20px",
          borderRadius: 999,
          backgroundColor: `${COLORS.accent}22`,
          color: COLORS.accentSoft,
          fontSize: 24,
          fontWeight: 700,
          letterSpacing: 2,
          textTransform: "uppercase",
          width: "fit-content",
          marginBottom: 36,
          opacity: interpolate(frame, [0.15 * fps, 0.6 * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        RSNA · V19
      </Interactive.Div>
      <Interactive.Div
        name="Title"
        premountFor={fps}
        style={{
          fontSize: 92,
          fontWeight: 800,
          lineHeight: 1.05,
          maxWidth: 1100,
          opacity: interpolate(frame, [0.2 * fps, 0.9 * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          translate: `0 ${interpolate(frame, [0.2 * fps, 0.9 * fps], [24, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          })}px`,
        }}
      >
        {title}
      </Interactive.Div>
      <Interactive.Div
        name="Subtitle"
        premountFor={fps}
        style={{
          marginTop: 28,
          fontSize: 36,
          color: COLORS.muted,
          maxWidth: 980,
          lineHeight: 1.4,
          opacity: interpolate(frame, [0.5 * fps, 1.2 * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {subtitle}
      </Interactive.Div>
    </AbsoluteFill>
  );
};

const openingSchema = {
  title: {
    type: "text-content",
    default: "DICOM Anonymizer",
    description: "Title",
  },
  subtitle: {
    type: "text-content",
    default: "Main features",
    description: "Subtitle",
  },
} as const satisfies InteractivitySchema;

export const OpeningScene = Interactive.withSchema({
  Component: OpeningSceneInner,
  componentName: "<OpeningScene>",
  schema: openingSchema,
  wrapInSequence: true,
});
