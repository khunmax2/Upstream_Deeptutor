'use client';

import { LINE_LIST, type LinePoolItem } from '@/configs/lines';
import { useI18n } from '@/lib/hooks/use-i18n';

interface LinePresetPickerProps {
  readonly onPick: (preset: LinePoolItem) => void;
}

function getPresetLabel(preset: LinePoolItem, t: (key: string) => string) {
  if (preset.isCubic) return t('editor.menu.lineCubic');
  if (preset.isCurve) return t('editor.menu.lineCurve');
  if (preset.isBroken2) return t('editor.menu.lineDoublePolyline');
  if (preset.isBroken) return t('editor.menu.linePolyline');
  if (preset.points[1] === 'arrow') return t('editor.menu.lineArrow');
  if (preset.points[1] === 'dot') return t('editor.menu.lineDotted');
  return preset.style === 'dashed' ? t('editor.menu.lineDashed') : t('editor.menu.lineStraight');
}

/** Renderer-editor insert palette for the existing DSL line presets. */
export function LinePresetPicker({ onPick }: LinePresetPickerProps) {
  const { t } = useI18n();
  return (
    <div className="grid grid-cols-5 gap-2" role="group" aria-label={t('editor.menu.linePresets')}>
      {LINE_LIST.flatMap((group) => group.children).map((preset, index) => {
        const label = getPresetLabel(preset, t);
        return (
          <button
            key={`${preset.path}-${index}`}
            type="button"
            aria-label={label}
            className="flex aspect-square items-center justify-center rounded-md border border-transparent p-2 text-zinc-600 hover:border-violet-300 hover:bg-violet-50 hover:text-violet-700 dark:text-zinc-300 dark:hover:border-violet-500/50 dark:hover:bg-violet-500/10"
            onClick={() => onPick(preset)}
          >
            <svg viewBox="0 0 20 20" className="h-7 w-7" aria-hidden="true">
              <path
                d={preset.path}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeDasharray={preset.style === 'dashed' ? '5 2.5' : undefined}
              />
            </svg>
          </button>
        );
      })}
    </div>
  );
}
