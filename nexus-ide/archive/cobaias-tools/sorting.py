def sort_list(input_list):
    """Sorts a list in ascending order and returns the sorted list.
    
    Args:
        input_list: The list to be sorted.
        
    Returns:
        A new list containing the elements of input_list in ascending order.
    """
    # Create a copy to avoid modifying the original list
    sorted_list = input_list.copy()
    sorted_list.sort()
    return sorted_list

# Example usage:
if __name__ == "__main__":
    # Test with a sample list
    test_list = [64, 34, 25, 12, 22, 11, 90]
    result = sort_list(test_list)
    print(f"Original list: {test_list}")
    print(f"Sorted list: {result}")