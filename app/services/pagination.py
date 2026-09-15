"""Utilidades compartidas para paginaciones compactas."""


def paginas_visibles(pagina_actual: int, total_paginas: int) -> list[int | None]:
    """Devuelve páginas y separadores sin renderizar una lista excesiva."""
    total_paginas = max(1, total_paginas)
    pagina_actual = max(1, min(pagina_actual, total_paginas))

    if total_paginas <= 11:
        return list(range(1, total_paginas + 1))

    if pagina_actual <= 5:
        candidatas = set(range(1, 8))
    elif pagina_actual >= total_paginas - 4:
        candidatas = set(range(total_paginas - 6, total_paginas + 1))
    else:
        candidatas = set(range(pagina_actual - 2, pagina_actual + 3))

    candidatas.update({1, 2, total_paginas - 1, total_paginas})
    ordenadas = sorted(candidatas)
    resultado: list[int | None] = []
    anterior = 0
    for numero in ordenadas:
        if anterior and numero - anterior > 1:
            resultado.append(None)
        resultado.append(numero)
        anterior = numero
    return resultado


def rango_registros(pagina: int, filas_por_pagina: int, total: int) -> tuple[int, int]:
    """Calcula el primer y último registro visible usando índices humanos."""
    if total <= 0:
        return 0, 0
    inicio = (pagina - 1) * filas_por_pagina + 1
    return inicio, min(pagina * filas_por_pagina, total)
