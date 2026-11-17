def decorate(function):
    return function


@decorate
def value():
    return 1


print(value())
