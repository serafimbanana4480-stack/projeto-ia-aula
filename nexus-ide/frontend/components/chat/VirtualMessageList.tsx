import { useLayoutEffect, useRef, useState, ReactNode } from "react";

interface VirtualMessageListProps<TMessage> {
  messages: TMessage[];
  renderItem: (message: TMessage, index: number) => ReactNode;
  initialLimit?: number;
  className?: string;
  /** Change when the same component instance receives a replacement snapshot. */
  resetKey?: string | number;
}

interface WindowState {
  resetKey: string | number | undefined;
  initialLimit: number;
  limit: number;
}

interface ScrollSnapshot {
  container: HTMLElement;
  height: number;
  top: number;
}

function findScrollContainer(element: HTMLElement | null): HTMLElement | null {
  let parent = element?.parentElement ?? null;
  while (parent) {
    const overflowY = window.getComputedStyle(parent).overflowY;
    if (overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay") {
      return parent;
    }
    parent = parent.parentElement;
  }
  return null;
}

/**
 * Performance-optimized message list with pagination.
 * Limits the number of rendered messages to improve performance.
 * Users can click "Load more" to see older messages.
 */
export default function VirtualMessageList<TMessage>({
  messages,
  renderItem,
  initialLimit = 50,
  className = "",
  resetKey,
}: VirtualMessageListProps<TMessage>) {
  const [windowState, setWindowState] = useState<WindowState>({
    resetKey,
    initialLimit,
    limit: initialLimit,
  });
  const rootRef = useRef<HTMLDivElement>(null);
  const pendingScrollSnapshotRef = useRef<ScrollSnapshot | null>(null);

  // Derive from the new identity during render so a replaced snapshot never
  // briefly renders with the previous snapshot's expanded window.
  const stateMatchesProps =
    windowState.resetKey === resetKey && windowState.initialLimit === initialLimit;
  const limit = stateMatchesProps ? windowState.limit : initialLimit;

  useLayoutEffect(() => {
    if (stateMatchesProps) return;
    setWindowState({ resetKey, initialLimit, limit: initialLimit });
  }, [initialLimit, resetKey, stateMatchesProps]);

  // Revealing older rows inserts content above the rows the user was reading.
  // Restore the old viewport position before paint to keep that message anchored.
  useLayoutEffect(() => {
    const snapshot = pendingScrollSnapshotRef.current;
    if (!snapshot) return;
    pendingScrollSnapshotRef.current = null;
    const heightDelta = snapshot.container.scrollHeight - snapshot.height;
    if (heightDelta !== 0) snapshot.container.scrollTop = snapshot.top + heightDelta;
  }, [limit]);

  const hasMore = messages.length > limit;

  const visibleMessages = messages.slice(-limit);
  const hiddenCount = messages.length - limit;

  const handleLoadMore = () => {
    if (!hasMore) return;
    const scrollContainer = findScrollContainer(rootRef.current);
    if (scrollContainer) {
      pendingScrollSnapshotRef.current = {
        container: scrollContainer,
        height: scrollContainer.scrollHeight,
        top: scrollContainer.scrollTop,
      };
    }
    setWindowState((previous) => {
      const currentLimit =
        previous.resetKey === resetKey && previous.initialLimit === initialLimit
          ? previous.limit
          : initialLimit;
      return {
        resetKey,
        initialLimit,
        limit: Math.min(currentLimit + initialLimit, messages.length),
      };
    });
  };

  return (
    <div ref={rootRef} className={className}>
      {hasMore && (
        <button
          type="button"
          onClick={handleLoadMore}
          className="w-full py-2 text-xs text-nexus-muted hover:text-nexus-text transition-colors"
        >
          Carregar mais {Math.min(initialLimit, hiddenCount)} mensagens ({hiddenCount} ocultas)
        </button>
      )}
      <div className="space-y-4">
        {visibleMessages.map((message, index) =>
          renderItem(message, messages.length - limit + index)
        )}
      </div>
    </div>
  );
}
