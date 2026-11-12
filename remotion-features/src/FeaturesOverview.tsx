import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { AbsoluteFill, useVideoConfig } from "remotion";
import { COLORS } from "./theme";
import { ClosingScene } from "./scenes/ClosingScene";
import { FeatureScene } from "./scenes/FeatureScene";
import { OpeningScene } from "./scenes/OpeningScene";
import { ProcessScene } from "./scenes/ProcessScene";

export const FeaturesOverview: React.FC = () => {
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <TransitionSeries>
        <TransitionSeries.Sequence
          name="Opening"
          durationInFrames={90}
          premountFor={fps}
        >
          <OpeningScene
            title="RSNA DICOM Anonymizer"
            subtitle="Remove protected identity information from medical imaging — then review, process, and send research-safe copies."
          />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence
          name="Deidentify"
          durationInFrames={96}
          premountFor={fps}
        >
          <FeatureScene
            eyebrow="Import"
            title="De-identify DICOM tags on import"
            body="Patient names, IDs, and other identifiers are replaced or removed by the project script. Dates are shifted consistently within a patient."
            accentColor={COLORS.accent}
          />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence
          name="Search"
          durationInFrames={84}
          premountFor={fps}
        >
          <FeatureScene
            eyebrow="Search"
            title="Bring studies in from folder or PACS"
            body="Import a local folder of DICOM files, or search a hospital imaging system and pull selected studies into the project."
            accentColor={COLORS.accentSoft}
          />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence
          name="View"
          durationInFrames={84}
          premountFor={fps}
        >
          <FeatureScene
            eyebrow="View"
            title="Browse Dataset and Series View"
            body="Inspect patients and series, open projections, check metadata, and QA before you process or send."
            accentColor={COLORS.highlight}
          />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence
          name="Process"
          durationInFrames={126}
          premountFor={fps}
        >
          <ProcessScene
            title="Process finishes what import cannot"
            item1="Embedded PHI — pixels, metadata, reports"
            item2="Harmonize study & series names"
            item3="Blur faces on eligible head exams"
            item4="AI Batch across a whole cohort"
          />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence
          name="Send"
          durationInFrames={84}
          premountFor={fps}
        >
          <FeatureScene
            eyebrow="Send"
            title="Export anonymized studies"
            body="Send research-safe copies to another system or cloud archive when processing looks good."
            accentColor={COLORS.warn}
          />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence
          name="Modes"
          durationInFrames={84}
          premountFor={fps}
        >
          <FeatureScene
            eyebrow="Modes"
            title="Desktop GUI or headless lab runs"
            body="Use the window for projects, review, and AI tools. Run headless receive or overnight AI batch on a configured project."
            accentColor={COLORS.accent}
          />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: 12 })}
        />
        <TransitionSeries.Sequence
          name="Closing"
          durationInFrames={78}
          premountFor={fps}
        >
          <ClosingScene
            title="Built for imaging research workflows"
            subtitle="DICOM Basic Profile defaults · MIDI-B aligned header checks · clinician manual at rsna.github.io/anonymizer"
          />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </AbsoluteFill>
  );
};
