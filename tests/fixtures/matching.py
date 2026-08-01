"""`match` shapes. Scores here are asserted against radon itself."""


def with_wildcard(cmd):
    match cmd:
        case "go":
            return 1
        case "stop":
            return 2
        case _:
            return 0


def with_capture(cmd):
    match cmd:
        case "go":
            return 1
        case other:
            return other


def no_default(cmd):
    match cmd:
        case "go":
            return 1
        case "stop":
            return 2


def only_wildcard(cmd):
    match cmd:
        case _:
            return 0


def nested_and_branchy(cmd, flag):
    total = 0
    if flag:
        total += 1
    match cmd:
        case {"kind": "a"}:
            for i in range(3):
                total += i
        case [x, y]:
            total += x + y
        case _:
            total -= 1
    return total
