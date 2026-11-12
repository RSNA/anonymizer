import { Composition, Folder } from "remotion";
import { FeatureCard } from "./components/FeatureCard";
import { FeaturesOverview } from "./FeaturesOverview";
import { ClosingScene } from "./scenes/ClosingScene";
import { FeatureScene } from "./scenes/FeatureScene";
import { OpeningScene } from "./scenes/OpeningScene";
import { ProcessScene } from "./scenes/ProcessScene";
import { COLORS } from "./theme";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="FeaturesOverview"
        component={FeaturesOverview}
        width={1920}
        height={1080}
        fps={30}
        durationInFrames={642}
      />
      <Folder name="Scenes">
        <Composition
          id="Opening"
          component={OpeningScene}
          width={1920}
          height={1080}
          fps={30}
          durationInFrames={90}
          defaultProps={{
            title: "RSNA DICOM Anonymizer",
            subtitle:
              "Remove protected identity information from medical imaging — then review, process, and send research-safe copies.",
          }}
        />
        <Composition
          id="Deidentify"
          component={FeatureScene}
          width={1920}
          height={1080}
          fps={30}
          durationInFrames={96}
          defaultProps={{
            eyebrow: "Import",
            title: "De-identify DICOM tags on import",
            body: "Patient names, IDs, and other identifiers are replaced or removed by the project script. Dates are shifted consistently within a patient.",
            accentColor: COLORS.accent,
          }}
        />
        <Composition
          id="Search"
          component={FeatureScene}
          width={1920}
          height={1080}
          fps={30}
          durationInFrames={84}
          defaultProps={{
            eyebrow: "Search",
            title: "Bring studies in from folder or PACS",
            body: "Import a local folder of DICOM files, or search a hospital imaging system and pull selected studies into the project.",
            accentColor: COLORS.accentSoft,
          }}
        />
        <Composition
          id="View"
          component={FeatureScene}
          width={1920}
          height={1080}
          fps={30}
          durationInFrames={84}
          defaultProps={{
            eyebrow: "View",
            title: "Browse Dataset and Series View",
            body: "Inspect patients and series, open projections, check metadata, and QA before you process or send.",
            accentColor: COLORS.highlight,
          }}
        />
        <Composition
          id="Process"
          component={ProcessScene}
          width={1920}
          height={1080}
          fps={30}
          durationInFrames={126}
          defaultProps={{
            title: "Process finishes what import cannot",
            item1: "Embedded PHI — pixels, metadata, reports",
            item2: "Harmonize study & series names",
            item3: "Blur faces on eligible head exams",
            item4: "AI Batch across a whole cohort",
          }}
        />
        <Composition
          id="Send"
          component={FeatureScene}
          width={1920}
          height={1080}
          fps={30}
          durationInFrames={84}
          defaultProps={{
            eyebrow: "Send",
            title: "Export anonymized studies",
            body: "Send research-safe copies to another system or cloud archive when processing looks good.",
            accentColor: COLORS.warn,
          }}
        />
        <Composition
          id="Modes"
          component={FeatureScene}
          width={1920}
          height={1080}
          fps={30}
          durationInFrames={84}
          defaultProps={{
            eyebrow: "Modes",
            title: "Desktop GUI or headless lab runs",
            body: "Use the window for projects, review, and AI tools. Run headless receive or overnight AI batch on a configured project.",
            accentColor: COLORS.accent,
          }}
        />
        <Composition
          id="Closing"
          component={ClosingScene}
          width={1920}
          height={1080}
          fps={30}
          durationInFrames={78}
          defaultProps={{
            title: "Built for imaging research workflows",
            subtitle:
              "DICOM Basic Profile defaults · MIDI-B aligned header checks · clinician manual at rsna.github.io/anonymizer",
          }}
        />
      </Folder>
      <Folder name="Elements">
        <Composition
          id="FeatureCard"
          component={FeatureCard}
          width={1920}
          height={1080}
          fps={30}
          durationInFrames={90}
          defaultProps={{
            eyebrow: "Import",
            title: "De-identify DICOM tags on import",
            body: "Patient names, IDs, and other identifiers are replaced or removed by the project script.",
            accentColor: COLORS.accent,
          }}
        />
      </Folder>
    </>
  );
};
