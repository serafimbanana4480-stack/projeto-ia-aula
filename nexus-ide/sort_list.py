"""Utility module providing a list sorting function."""

from __future__ import annotations

from typing import List, TypeVar, Callable, Optional

T = TypeVar("T")


def sort_list(
    items: List[T],
    *,
    reverse: bool = False,
    key: Optional[Callable[[T], object]] = None,
) -> List[T]:
    """Sort a list and return a new sorted list.

    Uses an iterative merge sort (O(n log n) time, O(n) space, stable).

    Args:
        items: The list of elements to sort.
        reverse: If True, the list is sorted in descending order.
        key: Optional function that extracts a comparison key from each element.

    Returns:
        A new list containing all elements in sorted order.

    Examples:
        >>> sort_list([3, 1, 2])
        [1, 2, 3]
        >>> sort_list([3, 1, 2], reverse=True)
        [3, 2, 1]
        >>> sort_list(["banana", "apple"], key=len)
        ['apple', 'banana']
    """
    if not items:
        return []

    # Build the list of (sort_key, original_index, value) tuples so the sort
    # is stable and respects the optional key function.
    indexed = [
        (key(item) if key else item, i, item)
        for i, item in enumerate(items)
    ]

    _merge_sort(indexed)

    if reverse:
        indexed.reverse()

    return [item for _, _, item in indexed]


def _merge_sort(arr: List[tuple]) -> None:
    """In-place iterative merge sort on a list of tuples.

    Tuples are compared element-wise; the first element is the sort key and
    the second element (original index) guarantees stability.
    """
    n = len(arr)
    width = 1
    while width < n:
        for i in range(0, n, 2 * width):
            mid = min(i + width, n)
            end = min(i + 2 * width, n)
            if mid < end:
                _merge(arr, i, mid, end)
        width *= 2


def _merge(arr: List[tuple], start: int, mid: int, end: int) -> None:
    """Merge two sorted sub-arrays arr[start:mid] and arr[mid:end]."""
    left = arr[start:mid]
    right = arr[mid:end]
    i = j = 0
    k = start
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            arr[k] = left[i]
            i += 1
        else:
            arr[k] = right[j]
            j += 1
        k += 1
    while i < len(left):
        arr[k] = left[i]
        i += 1
        k += 1
    while j < len(right):
        arr[k] = right[j]
        j += 1
        k += 1


if __name__ == "__main__":
    # Quick manual verification
    print(sort_list([5, 2, 9, 1, 5, 6]))
    print(sort_list([5, 2, 9, 1, 5, 6], reverse=True))
    print(sort_list(["banana", "apple", "cherry"], key=len))
    print(sort_list([]))