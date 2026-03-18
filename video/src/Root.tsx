import {Composition} from 'remotion';
import {HookePromo} from './HookePromo';

export const Root = () => {
  return (
    <Composition
      id="HookePromo"
      component={HookePromo}
      durationInFrames={450}
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
