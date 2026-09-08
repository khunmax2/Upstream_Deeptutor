import { cn } from '@/lib/utils';
import type { Experimental_GeneratedImage } from 'ai';
import { asset } from '@/lib/base-path';

export type ImageProps = Experimental_GeneratedImage & {
  className?: string;
  alt?: string;
};

export const Image = ({ base64, mediaType, ...props }: ImageProps) => (
  <img
    {...props}
    alt={props.alt}
    className={cn('h-auto max-w-full overflow-hidden rounded-md', props.className)}
    src={asset(`data:${mediaType};base64,${base64}`)}
  />
);
