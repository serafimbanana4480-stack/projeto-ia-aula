"""Módulo com funções utilitárias para ordenação de listas."""

from typing import List, TypeVar, Optional, Callable

T = TypeVar("T")


def sort_list(
    items: List[T],
    reverse: bool = False,
    key: Optional[Callable[[T], object]] = None,
) -> List[T]:
    """
    Ordena uma lista e devolve uma nova lista ordenada.

    A função não modifica a lista original (comportamento puramente funcional).

    Args:
        items: Lista de elementos a ordenar.
        reverse: Se True, ordena em ordem decrescente. Por defeito, False (crescente).
        key: Função opcional que extrai uma chave de comparação de cada elemento.
             Útil para ordenar por um atributo específico (ex: key=lambda x: x.id).

    Returns:
        Uma nova lista com os elementos ordenados.

    Raises:
        TypeError: Se os elementos não forem comparáveis entre si.

    Examples:
        >>> sort_list([3, 1, 4, 1, 5, 9, 2, 6])
        [1, 1, 2, 3, 4, 5, 6, 9]

        >>> sort_list([3, 1, 4], reverse=True)
        [4, 3, 1]

        >>> sort_list(['banana', 'abacaxi', 'laranja'], key=len)
        ['abacaxi', 'banana', 'laranja']

        >>> sort_list([])
        []
    """
    if items is None:
        raise TypeError("A lista fornecida é None; esperava uma lista.")

    # sorted() devolve uma nova lista, preservando a original intacta
    return sorted(items, key=key, reverse=reverse)


def sort_list_inplace(
    items: List[T],
    reverse: bool = False,
    key: Optional[Callable[[T], object]] = None,
) -> List[T]:
    """
    Ordena uma lista **in place** (modifica a lista original) e devolve a mesma lista.

    Útil quando se pretende evitar a cópia de memória de uma nova lista.

    Args:
        items: Lista de elementos a ordenar (será modificada).
        reverse: Se True, ordena em ordem decrescente.
        key: Função opcional de extração de chave.

    Returns:
        A mesma lista passada como argumento, agora ordenada.

    Examples:
        >>> data = [5, 2, 8, 1]
        >>> sort_list_inplace(data)
        [1, 2, 5, 8]
        >>> data  # a lista original foi modificada
        [1, 2, 5, 8]
    """
    if items is None:
        raise TypeError("A lista fornecida é None; esperava uma lista.")

    items.sort(key=key, reverse=reverse)
    return items


if __name__ == "__main__":
    # Demonstração rápida
    sample = [64, 34, 25, 12, 22, 11, 90]
    print("Lista original:     ", sample)
    print("Lista ordenada:     ", sort_list(sample))
    print("Lista original (não alterada):", sample)

    sample2 = [64, 34, 25, 12, 22, 11, 90]
    sort_list_inplace(sample2)
    print("Lista in-place:     ", sample2)

    print("Ordem decrescente:  ", sort_list(sample, reverse=True))
    print("Por comprimento:    ", sort_list(["aaa", "a", "aa"], key=len))