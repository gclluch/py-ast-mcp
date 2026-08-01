"""Deliberately awful module: every smell and hazard the quality tools look for."""

import asyncio


async def coro(x):
    return x * 2


def mutable_default(items=[], mapping={}, cache=dict()):
    items.append(1)
    return items, mapping, cache


def too_many_params(a, b, c, d, e, f, g):
    return a + b + c + d + e + f + g


def bare_except():
    try:
        return 1 / 0
    except:
        pass


def broad_except():
    try:
        return int("x")
    except Exception:
        return None


def shadowing(list, dict, id):
    type = list
    return type, dict, id


def compare_singletons(value, flag):
    if value == None:
        return False
    if flag == True:
        return True
    if flag != False:
        return True
    return value != None


def late_binding(names):
    handlers = []
    for name in names:
        handlers.append(lambda: name.upper())

        def handler():
            return name

        handlers.append(handler)
    return handlers


def validate(payload):
    assert isinstance(payload, dict), "payload must be a dict"
    assert "id" in payload
    return payload["id"]


def forgot_await():
    return coro(21)


def deeply_nested(rows):
    out = []
    for row in rows:
        if row:
            for cell in row:
                if cell:
                    while cell > 0:
                        if cell % 2 == 0:
                            out.append(cell)
                        cell -= 1
    return out


def long_and_complex(n):
    total = 0
    if n > 0:
        total += 1
    elif n < 0:
        total -= 1
    for i in range(n):
        if i % 2 == 0 and i % 3 == 0:
            total += i
        elif i % 5 == 0 or i % 7 == 0:
            total -= i
        else:
            total += 1
    while total > 100:
        total //= 2
    try:
        with open("/dev/null") as fh:
            fh.read()
    except OSError:
        total = 0
    except ValueError:
        total = -1
    values = [x for x in range(n) if x > 2 if x < 10]
    total += sum(values)
    total += 1 if n else 0
    assert total >= -1000
    line_a = 1
    line_b = 2
    line_c = 3
    line_d = 4
    line_e = 5
    line_f = 6
    line_g = 7
    line_h = 8
    line_i = 9
    line_j = 10
    line_k = 11
    line_l = 12
    line_m = 13
    line_n = 14
    line_o = 15
    line_p = 16
    line_q = 17
    line_r = 18
    line_s = 19
    line_t = 20
    line_u = 21
    line_v = 22
    line_w = 23
    return (
        total
        + line_a
        + line_b
        + line_c
        + line_d
        + line_e
        + line_f
        + line_g
        + line_h
        + line_i
        + line_j
        + line_k
        + line_l
        + line_m
        + line_n
        + line_o
        + line_p
        + line_q
        + line_r
        + line_s
        + line_t
        + line_u
        + line_v
        + line_w
    )


class GodClass:
    """Far too many responsibilities."""

    def m01(self):
        return 1

    def m02(self):
        return 2

    def m03(self):
        return 3

    def m04(self):
        return 4

    def m05(self):
        return 5

    def m06(self):
        return 6

    def m07(self):
        return 7

    def m08(self):
        return 8

    def m09(self):
        return 9

    def m10(self):
        return 10

    def m11(self):
        return 11

    def m12(self):
        return 12

    def m13(self):
        return 13

    def m14(self):
        return 14

    def m15(self):
        return 15

    def m16(self):
        return 16

    def m17(self):
        return 17

    def m18(self):
        return 18

    def m19(self):
        return 19

    def m20(self):
        return 20

    def m21(self):
        return 21

    def uses_state(self):
        return self.m01()


async def runner():
    await asyncio.sleep(0)
    coro(1)
    return await coro(2)
