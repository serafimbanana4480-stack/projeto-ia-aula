def sort_list(input_list):
    """Return a sorted copy of the input list.
    
    Args:
        input_list: List of comparable elements
        
    Returns:
        List sorted in ascending order
    """
    return sorted(input_list)

# Test the function
if __name__ == "__main__":
    # Test with numbers
    numbers = [3, 1, 4, 1, 5, 9, 2, 6]
    print(f"Original: {numbers}")
    print(f"Sorted: {sort_list(numbers)}")
    
    # Test with strings
    words = ["banana", "apple", "cherry", "date"]
    print(f"Original: {words}")
    print(f"Sorted: {sort_list(words)}")
    
    # Test with mixed types (should raise TypeError)
    try:
        mixed = [1, "two", 3]
        print(f"Mixed: {sort_list(mixed)}")
    except TypeError as e:
        print(f"Expected error for mixed types: {e}")