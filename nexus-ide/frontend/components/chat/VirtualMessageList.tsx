import { useState, ReactNode } from "react";

interface VirtualMessageListProps {
  messages: any[];
  renderItem: (message: any, index: number) => ReactNode;
  initialLimit?: number;
  className?: string;
}

/**
 * Performance-optimized message list with pagination.
 * Limits the number of rendered messages to improve performance.
 * Users can click "Load more" to see older messages.
 */
export default function VirtualMessageList({
  messages,
  renderItem,
  initialLimit = 50,
  className = "",
}: VirtualMessageListProps) {
  const [limit, setLimit] = useState(initialLimit);
  const hasMore = messages.length > limit;

  const visibleMessages = messages.slice(-limit);
  const hiddenCount = messages.length - limit;

  const handleLoadMore = () => {
    setLimit((prev) => Math.min(prev + initialLimit, messages.length));
  };

  return (
    <div className={className}>
      {hasMore && (
        <button
          onClick={handleLoadMore}
          className="w-full py-2 text-xs text-nexus-muted hover:text-nexus-text transition-colors"
        >
          Load {Math.min(initialLimit, hiddenCount)} more messages ({hiddenCount} hidden)
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