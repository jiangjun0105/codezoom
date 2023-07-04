from __future__ import annotations

GREETING = "Hi"


def foo():
    print(GREETING)


TEST = "test"


class Foo:
    a = 1
    b = 2

    def __init__(self):
        foo()

    def bar(self):
        print("bar")
        print("bar")
        print("bar")


if __name__ == "__main__":
    Foo()
