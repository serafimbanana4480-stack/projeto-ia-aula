def sort_list(lst):
    """
    Sorts a list and returns a new sorted list.
    
    Args:
        lst: A list of comparable elements
        
    Returns:
        A new list containing the sorted elements
    """
    if not isinstance(lst, list):
        raise TypeError("O argumento deve ser uma lista.")
    return sorted(lst)