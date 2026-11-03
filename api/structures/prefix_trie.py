class _TrieBranch:
    __slots__ = ("children", "word")

    def __init__(self):
        self.children = {}
        self.word = None  # la palabra original si aquí termina una; si no, None


class PrefixTrie:
    """Árbol de prefijos para buscar palabras por su comienzo.

    Cada nivel guarda un carácter, así que buscar un prefijo cuesta lo que mide el
    prefijo y no depende de cuántas palabras haya. La comparación no distingue
    mayúsculas de minúsculas (se usa ``casefold``), pero se devuelve la palabra tal
    como se insertó. Las palabras salen en orden alfabético.

    Complejidad (``m`` = largo de la palabra o del prefijo, ``r`` = resultados
    devueltos, ``t`` = nodos del subárbol del prefijo):
        insert(word) / contains(word) / delete(word) -- O(m)
        with_prefix(prefix) -- O(m + t log t), con t proporcional a los caracteres
            de las palabras que lo comparten (el log viene de ordenar cada nivel)
        with_prefix(prefix, limit=r) -- igual en el peor caso; corta al reunir r
        len() -- O(1)
        espacio -- O(total de caracteres insertados) en el peor caso
    """

    def __init__(self):
        self._root = _TrieBranch()
        self._size = 0

    def __len__(self):
        return self._size

    def __contains__(self, word):
        return self.contains(word)

    @staticmethod
    def _key(text):
        if not isinstance(text, str):
            raise TypeError("Solo se admiten textos.")
        return text.casefold()

    def insert(self, word):
        """Agrega ``word``; devuelve ``True`` si era nueva y ``False`` si ya estaba."""
        if not word:
            raise ValueError("La palabra no puede estar vacía.")
        branch = self._root
        for char in self._key(word):
            branch = branch.children.setdefault(char, _TrieBranch())
        if branch.word is not None:
            return False
        branch.word = word
        self._size += 1
        return True

    def _find(self, text):
        branch = self._root
        for char in self._key(text):
            branch = branch.children.get(char)
            if branch is None:
                return None
        return branch

    def contains(self, word):
        branch = self._find(word)
        return branch is not None and branch.word is not None

    def delete(self, word):
        """Quita ``word`` y poda las ramas que quedan vacías; ``True`` si existía."""
        key = self._key(word)
        path = [self._root]
        for char in key:
            branch = path[-1].children.get(char)
            if branch is None:
                return False
            path.append(branch)
        if path[-1].word is None:
            return False
        path[-1].word = None
        self._size -= 1
        for depth in range(len(key), 0, -1):
            branch = path[depth]
            if branch.word is not None or branch.children:
                break
            del path[depth - 1].children[key[depth - 1]]
        return True

    def with_prefix(self, prefix, limit=None):
        """Devuelve las palabras que empiezan por ``prefix`` (vacío = todas)."""
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 0):
            raise ValueError("El límite debe ser un entero mayor o igual que 0.")
        start = self._find(prefix)
        found = []
        if start is None or limit == 0:
            return found
        pending = [start]
        while pending:
            branch = pending.pop()
            if branch.word is not None:
                found.append(branch.word)
                if limit is not None and len(found) >= limit:
                    break
            # Se apilan al revés para que salgan en orden alfabético.
            for char in sorted(branch.children, reverse=True):
                pending.append(branch.children[char])
        return found
