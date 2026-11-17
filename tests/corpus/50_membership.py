"""`in` / `not in` across native lists and strings.

These cases pin operand order, negation, and substring matching.
"""

values = [5, 2, 9, 1, 7, 3]
print("in_list:", 7 in values)
print("not_present:", 42 in values)
print("not_in:", 42 not in values)
print("edge:", 9 in [1, 2, 3])

text = "Tarvos Python Compiler"
print("in_str:", "Python" in text)
print("str_absent:", "Zig" in text)
print("str_not_in:", "Zig" not in text)
