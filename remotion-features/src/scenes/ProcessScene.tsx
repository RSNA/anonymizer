import type React from "react";
import {
  AbsoluteFill,
  Interactive,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  type InteractivitySchema,
} from "remotion";
import { COLORS, FONT } from "../theme";

type ProcessSceneProps = {
  readonly title: string;
  readonly item1: string;
  readonly item2: string;
  readonly item3: string;
  readonly item4: string;
  readonly style?: React.CSSProperties;
};

const ProcessSceneInner: React.FC<ProcessSceneProps> = ({
  title,
  item1,
  item2,
  item3,
  item4,
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
        padding: "100px 120px",
        ...style,
      }}
    >
      <Interactive.Div
        name="ProcessTitle"
        premountFor={fps}
        style={{
          fontSize: 64,
          fontWeight: 800,
          marginBottom: 48,
          opacity: interpolate(frame, [0, 0.5 * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {title}
      </Interactive.Div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 28,
        }}
      >
        <Interactive.Div
          name="ProcessItem1"
          premountFor={fps}
          style={{
            padding: "36px 40px",
            borderRadius: 22,
            backgroundColor: COLORS.card,
            borderLeft: `8px solid ${COLORS.accentSoft}`,
            fontSize: 32,
            fontWeight: 600,
            lineHeight: 1.3,
            opacity: interpolate(frame, [0.3 * fps, 0.7 * fps], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            translate: `0 ${interpolate(frame, [0.3 * fps, 0.7 * fps], [18, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            })}px`,
          }}
        >
          {item1}
        </Interactive.Div>
        <Interactive.Div
          name="ProcessItem2"
          premountFor={fps}
          style={{
            padding: "36px 40px",
            borderRadius: 22,
            backgroundColor: COLORS.card,
            borderLeft: `8px solid ${COLORS.highlight}`,
            fontSize: 32,
            fontWeight: 600,
            lineHeight: 1.3,
            opacity: interpolate(frame, [0.55 * fps, 0.95 * fps], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            translate: `0 ${interpolate(
              frame,
              [0.55 * fps, 0.95 * fps],
              [18, 0],
              {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              },
            )}px`,
          }}
        >
          {item2}
        </Interactive.Div>
        <Interactive.Div
          name="ProcessItem3"
          premountFor={fps}
          style={{
            padding: "36px 40px",
            borderRadius: 22,
            backgroundColor: COLORS.card,
            borderLeft: `8px solid ${COLORS.warn}`,
            fontSize: 32,
            fontWeight: 600,
            lineHeight: 1.3,
            opacity: interpolate(frame, [0.8 * fps, 1.2 * fps], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            translate: `0 ${interpolate(frame, [0.8 * fps, 1.2 * fps], [18, 0], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            })}px`,
          }}
        >
          {item3}
        </Interactive.Div>
        <Interactive.Div
          name="ProcessItem4"
          premountFor={fps}
          style={{
            padding: "36px 40px",
            borderRadius: 22,
            backgroundColor: COLORS.card,
            borderLeft: `8px solid ${COLORS.accent}`,
            fontSize: 32,
            fontWeight: 600,
            lineHeight: 1.3,
            opacity: interpolate(frame, [1.05 * fps, 1.45 * fps], [0, 1], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
            translate: `0 ${interpolate(
              frame,
              [1.05 * fps, 1.45 * fps],
              [18, 0],
              {
                extrapolateLeft: "clamp",
                extrapolateRight: "clamp",
              },
            )}px`,
          }}
        >
          {item4}
        </Interactive.Div>
      </div>
    </AbsoluteFill>
  );
};

const processSchema = {
  title: {
    type: "text-content",
    default: "Process with AI",
    description: "Title",
  },
  item1: { type: "text-content", default: "", description: "Item 1" },
  item2: { type: "text-content", default: "", description: "Item 2" },
  item3: { type: "text-content", default: "", description: "Item 3" },
  item4: { type: "text-content", default: "", description: "Item 4" },
} as const satisfies InteractivitySchema;

export const ProcessScene = Interactive.withSchema({
  Component: ProcessSceneInner,
  componentName: "<ProcessScene>",
  schema: processSchema,
  wrapInSequence: true,
});
