import type React from "react";
import {
  AbsoluteFill,
  Interactive,
  useVideoConfig,
  type InteractivitySchema,
} from "remotion";
import { FeatureCard } from "../components/FeatureCard";
import { COLORS, FONT } from "../theme";

type FeatureSceneProps = {
  readonly eyebrow: string;
  readonly title: string;
  readonly body: string;
  readonly accentColor: string;
  readonly style?: React.CSSProperties;
};

const FeatureSceneInner: React.FC<FeatureSceneProps> = ({
  eyebrow,
  title,
  body,
  accentColor,
  style,
}) => {
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bgAlt,
        fontFamily: FONT,
        ...style,
      }}
    >
      <FeatureCard
        premountFor={fps}
        durationInFrames={4 * fps}
        eyebrow={eyebrow}
        title={title}
        body={body}
        accentColor={accentColor}
      />
    </AbsoluteFill>
  );
};

const featureSceneSchema = {
  eyebrow: { type: "text-content", default: "", description: "Eyebrow" },
  title: { type: "text-content", default: "", description: "Title" },
  body: { type: "text-content", default: "", description: "Body" },
  accentColor: {
    type: "color",
    default: COLORS.accent,
    description: "Accent",
  },
} as const satisfies InteractivitySchema;

export const FeatureScene = Interactive.withSchema({
  Component: FeatureSceneInner,
  componentName: "<FeatureScene>",
  schema: featureSceneSchema,
  wrapInSequence: true,
});
