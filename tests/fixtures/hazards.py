"""Hazards the first pass of find_errors stayed silent about."""


def comprehension_late_binding():
    return [lambda: i for i in range(3)]


def genexp_late_binding():
    return (lambda: g for g in range(3))


def dict_comprehension_late_binding():
    return {k: (lambda: k) for k in range(3)}


def loop_late_binding(names):
    out = []
    for name in names:
        out.append(lambda: name)
    return out


def bound_by_default_arg():
    """Correctly bound - must not be reported."""
    return [lambda i=i: i for i in range(3)]


def is_with_literals(x):
    if x is 5:
        return "int"
    if x is "text":
        return "str"
    if x is not 1.5:
        return "float"
    if x is (1, 2):
        return "tuple"
    return None


def is_with_singletons(x, flag):
    """Correct identity checks - must not be reported."""
    if x is None:
        return 0
    if flag is True or flag is False:
        return 1
    if x is ...:
        return 2
    return 3


def unreachable_by_superclass():
    try:
        return int("x")
    except Exception:
        return 0
    except ValueError:
        return 1


def unreachable_by_duplicate():
    try:
        return int("x")
    except ValueError:
        return 0
    except ValueError:
        return 1


def unreachable_in_tuple():
    try:
        return int("x")
    except (OSError, LookupError):
        return 0
    except KeyError:
        return 1


def ordered_correctly():
    """Specific first - must not be reported."""
    try:
        return int("x")
    except ValueError:
        return 0
    except TypeError:
        return 1
    except Exception:
        return 2


def unrelated_siblings():
    """Neither is a subclass of the other - must not be reported."""
    try:
        return int("x")
    except KeyError:
        return 0
    except IndexError:
        return 1
