import { useMemo } from 'react';
import { ElementTypes, type PPTElement } from '@openmaic/dsl';
import { ImageElement } from '../../components/element/ImageElement';
import { TextElement } from '../../components/element/TextElement';
import { LineElement } from '../../components/element/LineElement';
import { ShapeElement } from '../../components/element/ShapeElement';
import { ChartElement } from '../../components/element/ChartElement';
import { LatexElement } from '../../components/element/LatexElement';
import { useI18n } from '@/lib/hooks/use-i18n';
import { TableElement } from '../../components/element/TableElement';
import { VideoElement } from '../../components/element/VideoElement';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuShortcut,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';
import { ElementOrderCommands, ElementAlignCommands } from '@/lib/types/edit';
import { useCanvasOperations } from '@/lib/hooks/use-canvas-operations';
import { editableElementDomId, elementIdAttributes } from '../../element-dom';

export interface ContextmenuItem {
  text?: string;
  subText?: string;
  divider?: boolean;
  disable?: boolean;
  hide?: boolean;
  children?: ContextmenuItem[];
  handler?: () => void;
}

interface EditableElementProps {
  readonly elementInfo: PPTElement;
  readonly elementIndex: number;
  readonly isMultiSelect: boolean;
  readonly selectElement: (
    e: React.MouseEvent | React.TouchEvent,
    element: PPTElement,
    canMove?: boolean,
  ) => void;
  readonly openLinkDialog: () => void;
}

export function EditableElement({
  elementInfo,
  elementIndex,
  isMultiSelect,
  selectElement,
  openLinkDialog,
}: EditableElementProps) {
  const CurrentElementComponent = useMemo(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- element components have varying prop signatures
    const elementTypeMap: Record<string, any> = {
      [ElementTypes.IMAGE]: ImageElement,
      [ElementTypes.TEXT]: TextElement,
      [ElementTypes.SHAPE]: ShapeElement,
      [ElementTypes.LINE]: LineElement,
      [ElementTypes.CHART]: ChartElement,
      [ElementTypes.LATEX]: LatexElement,
      [ElementTypes.TABLE]: TableElement,
      [ElementTypes.VIDEO]: VideoElement,
      // TODO: Add other element types
      // [ElementTypes.AUDIO]: AudioElement,
    };
    return elementTypeMap[elementInfo.type] || null;
  }, [elementInfo.type]);

  const {
    copyElement,
    pasteElement,
    cutElement,
    deleteElement,
    lockElement,
    unlockElement,
    selectAllElements,
    alignElementToCanvas,
    orderElement,
    combineElements,
    uncombineElements,
  } = useCanvasOperations();

  const { t } = useI18n();

  const contextmenus = (): ContextmenuItem[] => {
    if (elementInfo.lock) {
      return [
        {
          text: t('editor.menu.unlock'),
          handler: () => unlockElement(elementInfo),
        },
      ];
    }

    return [
      {
        text: t('editor.menu.cut'),
        subText: 'Ctrl + X',
        handler: cutElement,
      },
      {
        text: t('editor.menu.copy'),
        subText: 'Ctrl + C',
        handler: copyElement,
      },
      {
        text: t('editor.menu.paste'),
        subText: 'Ctrl + V',
        handler: pasteElement,
      },
      { divider: true },
      {
        text: t('editor.menu.alignHorizontalCenter'),
        handler: () => alignElementToCanvas(ElementAlignCommands.HORIZONTAL),
        children: [
          {
            text: t('editor.menu.alignCenter'),
            handler: () => alignElementToCanvas(ElementAlignCommands.CENTER),
          },
          {
            text: t('editor.menu.alignHorizontalCenter'),
            handler: () => alignElementToCanvas(ElementAlignCommands.HORIZONTAL),
          },
          {
            text: t('editor.menu.alignLeft'),
            handler: () => alignElementToCanvas(ElementAlignCommands.LEFT),
          },
          {
            text: t('editor.menu.alignRight'),
            handler: () => alignElementToCanvas(ElementAlignCommands.RIGHT),
          },
        ],
      },
      {
        text: t('editor.menu.alignVerticalCenter'),
        handler: () => alignElementToCanvas(ElementAlignCommands.VERTICAL),
        children: [
          {
            text: t('editor.menu.alignCenter'),
            handler: () => alignElementToCanvas(ElementAlignCommands.CENTER),
          },
          {
            text: t('editor.menu.alignVerticalCenter'),
            handler: () => alignElementToCanvas(ElementAlignCommands.VERTICAL),
          },
          {
            text: t('editor.menu.alignTop'),
            handler: () => alignElementToCanvas(ElementAlignCommands.TOP),
          },
          {
            text: t('editor.menu.alignBottom'),
            handler: () => alignElementToCanvas(ElementAlignCommands.BOTTOM),
          },
        ],
      },
      { divider: true },
      {
        text: t('editor.menu.bringToFront'),
        disable: isMultiSelect && !elementInfo.groupId,
        handler: () => orderElement(elementInfo, ElementOrderCommands.TOP),
        children: [
          {
            text: t('editor.menu.bringToFront'),
            handler: () => orderElement(elementInfo, ElementOrderCommands.TOP),
          },
          {
            text: t('editor.menu.bringForward'),
            handler: () => orderElement(elementInfo, ElementOrderCommands.UP),
          },
        ],
      },
      {
        text: t('editor.menu.sendToBack'),
        disable: isMultiSelect && !elementInfo.groupId,
        handler: () => orderElement(elementInfo, ElementOrderCommands.BOTTOM),
        children: [
          {
            text: t('editor.menu.sendToBack'),
            handler: () => orderElement(elementInfo, ElementOrderCommands.BOTTOM),
          },
          {
            text: t('editor.menu.sendBackward'),
            handler: () => orderElement(elementInfo, ElementOrderCommands.DOWN),
          },
        ],
      },
      { divider: true },
      {
        text: t('editor.menu.setLink'),
        handler: openLinkDialog,
        disable: true,
      },
      {
        text: elementInfo.groupId ? t('editor.menu.ungroup') : t('editor.menu.group'),
        subText: 'Ctrl + G',
        handler: elementInfo.groupId ? uncombineElements : combineElements,
        hide: !isMultiSelect,
      },
      {
        text: t('editor.menu.selectAll'),
        subText: 'Ctrl + A',
        handler: selectAllElements,
      },
      {
        text: t('editor.menu.lock'),
        subText: 'Ctrl + L',
        handler: lockElement,
      },
      {
        text: t('editor.menu.delete'),
        subText: 'Delete',
        handler: deleteElement,
      },
    ];
  };

  if (!CurrentElementComponent) {
    return (
      <div
        id={editableElementDomId(elementInfo.id)}
        {...elementIdAttributes(elementInfo.id)}
        className="editable-element absolute"
        style={{
          zIndex: elementIndex,
          left: elementInfo.left + 'px',
          top: elementInfo.top + 'px',
          width: elementInfo.width + 'px',
        }}
      >
        <div className="p-2 bg-gray-100 border border-gray-300 text-xs text-gray-500">
          {elementInfo.type} element (not implemented)
        </div>
      </div>
    );
  }

  return (
    <div
      id={editableElementDomId(elementInfo.id)}
      {...elementIdAttributes(elementInfo.id)}
      className="editable-element absolute"
      style={{
        zIndex: elementIndex,
      }}
    >
      <ContextMenu>
        <ContextMenuTrigger>
          <CurrentElementComponent elementInfo={elementInfo} selectElement={selectElement} />
        </ContextMenuTrigger>
        <ContextMenuContent>
          {contextmenus().map((item, index) => {
            if (item.divider) {
              return <ContextMenuSeparator key={index} />;
            }

            // If has children, use submenu component
            if (item.children && item.children.length > 0) {
              return (
                <ContextMenuSub key={index}>
                  <ContextMenuSubTrigger disabled={item.disable} hidden={item.hide}>
                    {item.text}
                    {item.subText && <ContextMenuShortcut>{item.subText}</ContextMenuShortcut>}
                  </ContextMenuSubTrigger>
                  <ContextMenuSubContent>
                    {item.children.map((child, childIndex) =>
                      child.divider ? (
                        <ContextMenuSeparator key={childIndex} />
                      ) : (
                        <ContextMenuItem
                          key={childIndex}
                          onClick={(e) => {
                            e.stopPropagation();
                            child.handler?.();
                          }}
                          disabled={child.disable}
                          hidden={child.hide}
                        >
                          {child.text}
                          {child.subText && (
                            <ContextMenuShortcut>{child.subText}</ContextMenuShortcut>
                          )}
                        </ContextMenuItem>
                      ),
                    )}
                  </ContextMenuSubContent>
                </ContextMenuSub>
              );
            }

            // Regular menu item
            return (
              <ContextMenuItem
                key={index}
                onClick={(e) => {
                  e.stopPropagation();
                  item.handler?.();
                }}
                disabled={item.disable}
                hidden={item.hide}
              >
                {item.text}
                {item.subText && <ContextMenuShortcut>{item.subText}</ContextMenuShortcut>}
              </ContextMenuItem>
            );
          })}
        </ContextMenuContent>
      </ContextMenu>
    </div>
  );
}
