from __future__ import annotations

GREETING = "Hi"


def foo():
    print(GREETING)


TEST = "hello"


class Bar:
    test = TEST


class Foo(Bar):
    a = 1
    b = 2

    def __init__(self):
        foo()

    def bar(self):
        print(self.test)


if __name__ == "__main__":
    Foo()
