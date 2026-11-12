import type React from "react";
import {
  Interactive,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  type InteractivitySchema,
} from "remotion";
import { COLORS, FONT } from "../theme";

type FeatureCardProps = {
  readonly eyebrow: string;
  readonly title: string;
  readonly body: string;
  readonly accentColor: string;
  readonly style?: React.CSSProperties;
};

const FeatureCardInner: React.FC<FeatureCardProps> = ({
  eyebrow,
  title,
  body,
  accentColor,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <Interactive.Div
      name="FeatureCard"
      style={{
        position: "absolute",
        left: 120,
        right: 120,
        top: 160,
        bottom: 140,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        gap: 28,
        padding: "56px 64px",
        borderRadius: 28,
        backgroundColor: COLORS.card,
        border: `1px solid ${accentColor}55`,
        boxShadow: `0 24px 80px ${accentColor}22`,
        fontFamily: FONT,
        color: COLORS.text,
        opacity: interpolate(frame, [0, 0.6 * fps], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        }),
        translate: `0 ${interpolate(frame, [0, 0.7 * fps], [28, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })}px`,
        ...style,
      }}
    >
      <div
        style={{
          width: 72,
          height: 8,
          borderRadius: 999,
          backgroundColor: accentColor,
        }}
      />
      <div
        style={{
          fontSize: 28,
          letterSpacing: 4,
          textTransform: "uppercase",
          color: accentColor,
          fontWeight: 700,
        }}
      >
        {eyebrow}
      </div>
      <div
        style={{
          fontSize: 72,
          lineHeight: 1.1,
          fontWeight: 700,
          maxWidth: 980,
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontSize: 34,
          lineHeight: 1.35,
          color: COLORS.muted,
          maxWidth: 960,
          fontWeight: 500,
        }}
      >
        {body}
      </div>
    </Interactive.Div>
  );
};

const featureCardSchema = {
  eyebrow: { type: "text-content", default: "", description: "Eyebrow" },
  title: { type: "text-content", default: "", description: "Title" },
  body: { type: "text-content", default: "", description: "Body" },
  accentColor: {
    type: "color",
    default: COLORS.accent,
    description: "Accent",
  },
} as const satisfies InteractivitySchema;

export const FeatureCard = Interactive.withSchema({
  Component: FeatureCardInner,
  componentName: "<FeatureCard>",
  schema: featureCardSchema,
  wrapInSequence: true,
});
