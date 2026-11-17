def first(value: int) -> int:
    if value == 0:
        return 0
    return second(value - 1)


def second(value: int) -> int:
    if value == 0:
        return 1
    return first(value - 1)


print(first(4))
