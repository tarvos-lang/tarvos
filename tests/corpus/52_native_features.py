import json
import math
import os
import time

value = 4
print(2 if value > 2 else 1)
print((value, value + 1))
print([item * 2 for item in range(3)])
print([1, 2, 3, 4][1:3])
print({"a": 1, "b": 2})
print(math.floor(math.pi))
print(json.dumps({"answer": 42}))
print(json.dumps({"answer": value}))
print(os.path.join("left", "right"))
print(os.path.exists("."))
print(time.perf_counter() >= 0)
print(f"value={value}")


def add(left: int, right: int) -> int:
    return left + right


print(add(right=2, left=3))


def factorial(number: int) -> int:
    if number <= 1:
        return 1
    return number * factorial(number - 1)


print(factorial(5))


def is_even(number: int) -> bool:
    if number == 0:
        return True
    return is_odd(number - 1)


def is_odd(number: int) -> bool:
    if number == 0:
        return False
    return is_even(number - 1)


print(is_even(8))
