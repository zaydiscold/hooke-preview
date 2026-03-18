import React from 'react';
import {
  AbsoluteFill,
  Easing,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

const palette = {
  bg: '#f3ecd9',
  bgDeep: '#eadfc8',
  ink: '#171615',
  muted: '#685f52',
  green: '#0f8b5f',
  blue: '#2a6f97',
  rust: '#b45a3c',
  panel: 'rgba(255, 249, 239, 0.84)',
};

const paperBackground: React.CSSProperties = {
  backgroundColor: palette.bg,
  backgroundImage: [
    'radial-gradient(circle at 15% 20%, rgba(15,139,95,0.10), transparent 28%)',
    'radial-gradient(circle at 82% 14%, rgba(42,111,151,0.10), transparent 24%)',
    'radial-gradient(circle at 50% 110%, rgba(180,90,60,0.08), transparent 30%)',
    'linear-gradient(rgba(25,24,23,0.05) 1px, transparent 1px)',
    'linear-gradient(90deg, rgba(25,24,23,0.05) 1px, transparent 1px)',
  ].join(','),
  backgroundSize: 'auto, auto, auto, 28px 28px, 28px 28px',
};

const easeOut = Easing.out(Easing.cubic);

const SceneTitle: React.FC<{
  kicker: string;
  title: string;
  body: string;
  accent?: string;
}> = ({kicker, title, body, accent = palette.green}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const reveal = spring({
    frame,
    fps,
    config: {damping: 200},
    durationInFrames: 28,
  });
  const shift = interpolate(reveal, [0, 1], [28, 0]);

  return (
    <div
      style={{
        width: 720,
        padding: '28px 34px',
        border: `3px solid ${palette.ink}`,
        background: palette.panel,
        boxShadow: '16px 16px 0 rgba(23,22,21,0.08)',
        transform: `translateY(${shift}px)`,
        opacity: reveal,
      }}
    >
      <div
        style={{
          fontFamily: 'Menlo, IBM Plex Mono, monospace',
          fontSize: 20,
          letterSpacing: '0.22em',
          textTransform: 'uppercase',
          color: palette.muted,
          marginBottom: 18,
        }}
      >
        {kicker}
      </div>
      <div
        style={{
          fontFamily: 'Iowan Old Style, Georgia, serif',
          fontSize: 76,
          lineHeight: 0.92,
          letterSpacing: '-0.05em',
          textTransform: 'uppercase',
          color: palette.ink,
          marginBottom: 18,
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontFamily: 'Menlo, IBM Plex Mono, monospace',
          fontSize: 29,
          lineHeight: 1.5,
          color: palette.ink,
        }}
      >
        {body}
      </div>
      <div
        style={{
          marginTop: 20,
          width: 180,
          height: 8,
          background: accent,
        }}
      />
    </div>
  );
};

const ScreenshotCard: React.FC<{
  src: string;
  frameOffset?: number;
  x: number;
  y: number;
  width: number;
  rotate?: number;
  startScale?: number;
  endScale?: number;
}> = ({
  src,
  frameOffset = 0,
  x,
  y,
  width,
  rotate = 0,
  startScale = 1.08,
  endScale = 1,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const local = Math.max(frame - frameOffset, 0);
  const enter = spring({
    frame: local,
    fps,
    config: {damping: 200},
    durationInFrames: 32,
  });
  const scale = interpolate(local, [0, 90], [startScale, endScale], {
    easing: easeOut,
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = interpolate(enter, [0, 1], [0, 1]);
  const lift = interpolate(enter, [0, 1], [34, 0]);

  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        width,
        border: `3px solid ${palette.ink}`,
        background: 'rgba(255,252,245,0.94)',
        boxShadow: '18px 18px 0 rgba(23,22,21,0.08)',
        overflow: 'hidden',
        transform: `translateY(${lift}px) rotate(${rotate}deg) scale(${scale})`,
        opacity,
      }}
    >
      <Img src={src} style={{width: '100%', display: 'block'}} />
    </div>
  );
};

const LabelPill: React.FC<{
  text: string;
  x: number;
  y: number;
  color?: string;
}> = ({text, x, y, color = palette.green}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [10, 22], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        left: x,
        top: y,
        padding: '10px 16px',
        border: `2px solid ${palette.ink}`,
        background: 'rgba(255,249,235,0.96)',
        fontFamily: 'Menlo, IBM Plex Mono, monospace',
        fontSize: 18,
        letterSpacing: '0.14em',
        textTransform: 'uppercase',
        color,
        opacity,
      }}
    >
      {text}
    </div>
  );
};

export const HookePromo: React.FC = () => {
  const frame = useCurrentFrame();
  const vignette = interpolate(frame, [0, 450], [0.04, 0.12], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={paperBackground}>
      <AbsoluteFill
        style={{
          background:
            `radial-gradient(circle at center, transparent 44%, rgba(20,18,15,${vignette}) 100%)`,
        }}
      />

      <Sequence from={0} durationInFrames={120} premountFor={30}>
        <AbsoluteFill style={{padding: 84}}>
          <div
            style={{
              position: 'absolute',
              inset: 0,
              border: `3px solid rgba(23,22,21,0.18)`,
              margin: 40,
            }}
          />
          <SceneTitle
            kicker="Hooke preview"
            title="Hard science questions need more than a quick answer."
            body="Hooke turns one prompt into literature, relevant data, and an experiment-ready starting point."
          />
          <ScreenshotCard
            src={staticFile('assets/hooke-home.png')}
            x={930}
            y={110}
            width={820}
            rotate={-1.8}
            startScale={1.12}
            endScale={1.02}
          />
          <LabelPill text="Ask the question" x={1040} y={82} />
        </AbsoluteFill>
      </Sequence>

      <Sequence from={105} durationInFrames={155} premountFor={30}>
        <AbsoluteFill style={{padding: 84}}>
          <SceneTitle
            kicker="From prompt to pipeline"
            title="Type once. Watch the research stack move."
            body="Hooke classifies the job, works through literature and genomic routes when needed, and keeps the workflow visible while it runs."
            accent={palette.blue}
          />
          <ScreenshotCard
            src={staticFile('assets/hooke-result.png')}
            frameOffset={6}
            x={890}
            y={96}
            width={860}
            rotate={1.2}
            startScale={1.08}
            endScale={0.98}
          />
          <LabelPill text="Pipeline in view" x={1180} y={86} color={palette.blue} />
          <div
            style={{
              position: 'absolute',
              left: 110,
              bottom: 100,
              width: 650,
              display: 'flex',
              gap: 18,
              fontFamily: 'Menlo, IBM Plex Mono, monospace',
              fontSize: 21,
              color: palette.ink,
            }}
          >
            {['orchestrator', 'literature', 'genomic', 'synthesis'].map((item, index) => {
              const on = interpolate(frame, [120 + index * 10, 132 + index * 10], [0.35, 1], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });
              return (
                <div
                  key={item}
                  style={{
                    padding: '10px 14px',
                    border: `2px solid ${palette.ink}`,
                    background: `rgba(255,249,235,${on})`,
                  }}
                >
                  {item}
                </div>
              );
            })}
          </div>
        </AbsoluteFill>
      </Sequence>

      <Sequence from={250} durationInFrames={200} premountFor={30}>
        <AbsoluteFill style={{padding: 84}}>
          <ScreenshotCard
            src={staticFile('assets/hooke-result.png')}
            x={90}
            y={120}
            width={1080}
            rotate={-0.6}
            startScale={1.04}
            endScale={0.94}
          />
          <div
            style={{
              position: 'absolute',
              right: 110,
              top: 118,
              width: 620,
              display: 'flex',
              flexDirection: 'column',
              gap: 24,
            }}
          >
            <SceneTitle
              kicker="What lands at the end"
              title="A brief you can actually use."
              body="Findings. Research gaps. References. A concrete next experiment. Built for people who still have to do the work after the browser tab closes."
              accent={palette.rust}
            />
          </div>
          <div
            style={{
              position: 'absolute',
              right: 120,
              bottom: 116,
              display: 'flex',
              gap: 18,
              fontFamily: 'Menlo, IBM Plex Mono, monospace',
              fontSize: 20,
            }}
          >
            {[
              {text: 'citations', color: palette.green},
              {text: 'research gaps', color: palette.blue},
              {text: 'next experiment', color: palette.rust},
            ].map((item, index) => {
              const pop = spring({
                frame: frame - 285 - index * 8,
                fps: 30,
                config: {damping: 200},
                durationInFrames: 24,
              });
              return (
                <div
                  key={item.text}
                  style={{
                    padding: '12px 16px',
                    border: `2px solid ${palette.ink}`,
                    background: 'rgba(255,249,235,0.94)',
                    color: item.color,
                    transform: `scale(${interpolate(pop, [0, 1], [0.8, 1])})`,
                    opacity: pop,
                  }}
                >
                  {item.text}
                </div>
              );
            })}
          </div>
        </AbsoluteFill>
      </Sequence>
    </AbsoluteFill>
  );
};
