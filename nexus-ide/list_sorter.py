"""Utility functions for sorting lists."""


def sort_list(lst, reverse=False, key=None):
    """Sort a list in-place or return a new sorted list.

    Args:
        lst: The list to sort.
        reverse: If True, sort in descending order.
        key: A function to extract a comparison key from each element.

    Returns:
        The sorted list (new list if reverse=False, otherwise modifies in-place).
    """
    # Make a copy to avoid mutating the original unless explicitly desired
    result = list(lst)
    result.sort(reverse=reverse, key=key)
    return result


def bubble_sort(lst):
    """Bubble sort implementation for educational purposes.

    Args:
        lst: The list to sort.

    Returns:
        A new sorted list using bubble sort algorithm.
    """
    arr = list(lst)
    n = len(arr)
    for i in range(n):
        swapped = False
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
                swapped = True
        if not swapped:
            break
    return arr


if __name__ == "__main__":
    # Example usage
    data = [5, 2, 9, 1, 5, 6]
    print("Original:", data)
    print("Sorted (asc):", sort_list(data))
    print("Sorted (desc):", sort_list(data, reverse=True))
    print("With key (by length):", sort_list([("apple", 5), ("banana", 3)], key=lambda x: x[1]))
