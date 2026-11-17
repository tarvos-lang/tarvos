for i in range(5):
    if i % 2 == 0:
        pass
    else:
        print("odd:", i)

try:
    x = 10 / 2
    print("divided:", x)
except ZeroDivisionError:
    print("never")
finally:
    pass

print("nested:", "done" if False else "done")
print("pass works")