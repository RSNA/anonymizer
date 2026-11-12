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

type ClosingSceneProps = {
  readonly title: string;
  readonly subtitle: string;
  readonly style?: React.CSSProperties;
};

const ClosingSceneInner: React.FC<ClosingSceneProps> = ({
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
        alignItems: "center",
        textAlign: "center",
        padding: 120,
        ...style,
      }}
    >
      <Interactive.Div
        name="ClosingTitle"
        premountFor={fps}
        style={{
          fontSize: 72,
          fontWeight: 800,
          opacity: interpolate(frame, [0, 0.6 * fps], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {title}
      </Interactive.Div>
      <Interactive.Div
        name="ClosingSubtitle"
        premountFor={fps}
        style={{
          marginTop: 24,
          fontSize: 34,
          color: COLORS.muted,
          maxWidth: 900,
          opacity: interpolate(frame, [0.3 * fps, 0.9 * fps], [0, 1], {
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

const closingSchema = {
  title: { type: "text-content", default: "", description: "Title" },
  subtitle: { type: "text-content", default: "", description: "Subtitle" },
} as const satisfies InteractivitySchema;

export const ClosingScene = Interactive.withSchema({
  Component: ClosingSceneInner,
  componentName: "<ClosingScene>",
  schema: closingSchema,
  wrapInSequence: true,
});
