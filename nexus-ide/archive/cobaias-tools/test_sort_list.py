"""Testes para as funções de ordenação do módulo sort_list."""

import pytest
from sort_list import sort_list, sort_list_inplace


class TestSortList:
    """Testes para a função sort_list (não modifica a original)."""

    def test_sort_basic(self):
        assert sort_list([3, 1, 4, 1, 5, 9, 2, 6]) == [1, 1, 2, 3, 4, 5, 6, 9]

    def test_sort_empty_list(self):
        assert sort_list([]) == []

    def test_sort_single_element(self):
        assert sort_list([42]) == [42]

    def test_sort_reverse(self):
        assert sort_list([3, 1, 4], reverse=True) == [4, 3, 1]

    def test_sort_with_key(self):
        assert sort_list(["banana", "abacaxi", "laranja"], key=len) == [
            "abacaxi",
            "banana",
            "laranja",
        ]

    def test_sort_does_not_modify_original(self):
        original = [3, 1, 4]
        result = sort_list(original)
        assert original == [3, 1, 4]
        assert result == [1, 3, 4]

    def test_sort_none_raises_type_error(self):
        with pytest.raises(TypeError):
            sort_list(None)

    def test_sort_already_sorted(self):
        assert sort_list([1, 2, 3, 4, 5]) == [1, 2, 3, 4, 5]

    def test_sort_reverse_already_sorted(self):
        assert sort_list([1, 2, 3, 4, 5], reverse=True) == [5, 4, 3, 2, 1]

    def test_sort_negative_numbers(self):
        assert sort_list([-3, -1, -4, -1, -5]) == [-5, -4, -3, -1, -1]

    def test_sort_mixed_positive_negative(self):
        assert sort_list([-3, 1, -4, 0, 5]) == [-4, -3, 0, 1, 5]


class TestSortListInplace:
    """Testes para a função sort_list_inplace (modifica a original)."""

    def test_sort_inplace_basic(self):
        data = [5, 2, 8, 1]
        result = sort_list_inplace(data)
        assert result == [1, 2, 5, 8]
        assert data == [1, 2, 5, 8]

    def test_sort_inplace_empty(self):
        data = []
        result = sort_list_inplace(data)
        assert result == []
        assert data == []

    def test_sort_inplace_reverse(self):
        data = [1, 3, 2]
        result = sort_list_inplace(data, reverse=True)
        assert result == [3, 2, 1]
        assert data == [3, 2, 1]

    def test_sort_inplace_with_key(self):
        data = ["aaa", "a", "aa"]
        result = sort_list_inplace(data, key=len)
        assert result == ["a", "aa", "aaa"]
        assert data == ["a", "aa", "aaa"]

    def test_sort_inplace_none_raises_type_error(self):
        with pytest.raises(TypeError):
            sort_list_inplace(None)

    def test_sort_inplace_returns_same_object(self):
        data = [3, 1, 2]
        result = sort_list_inplace(data)
        assert result is data