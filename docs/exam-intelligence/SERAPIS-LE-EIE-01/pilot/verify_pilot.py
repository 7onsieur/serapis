"""Deterministic verification for the SERAPIS-LE-EIE-01 exploratory pilot.

Research artefact only (not part of the Serapis application). Requires sympy:
    python3 -m venv /tmp/v && /tmp/v/bin/pip install sympy
    /tmp/v/bin/python verify_pilot.py pilot_questions.json > verification_results.json

For each question this recomputes the answer from the question's own algebra,
independently of the written worked solution, and also checks the mark total
and that the quadratic has no integer-factorisable shortcut where claimed.
"""
import json
import sys
from sympy import (Rational, Symbol, simplify, sqrt, sympify, solve, expand, Poly,
                   N, minimum, discriminant, S)

def num(s):
    return sympify(s, rational=True)

def roots_close(found, expected, tol=Rational(1, 10**12)):
    f = sorted(found, key=lambda r: float(N(r, 30)))
    e = sorted(expected, key=lambda r: float(N(r, 30)))
    return len(f) == len(e) and all(abs(N(a - b, 40)) < 1e-20 for a, b in zip(f, e))

def rnd_dp(v, dp):
    return str(round(float(N(v, 30)), dp))

def rnd_sf(v, sf):
    from math import floor, log10
    x = float(N(v, 30))
    if x == 0:
        return "0"
    d = sf - int(floor(log10(abs(x)))) - 1
    return str(round(x, d))

def check(q):
    c = q["check"]
    out = []
    t = c["type"]
    if t == "solve":
        x = Symbol(c["var"])
        p = num(c["poly"])
        found = solve(p, x)
        exp = [num(e) for e in c["expected"]]
        out.append(("sympy roots equal expected", roots_close(found, exp)))
        out.append(("every expected root substitutes to 0 exactly", all(simplify(p.subs(x, e)) == 0 for e in exp)))
        if "factor_identity" in c:
            a, b = c["factor_identity"]
            out.append(("factor identity expands equal", expand(num(a) - num(b)) == 0))
        if c.get("no_rational_roots"):
            out.append(("no rational root (not integer-factorisable)", all(not r.is_rational for r in found)))
    elif t == "round":
        x = Symbol(c["var"])
        found = solve(num(c["poly"]), x)
        got = sorted(rnd_dp(r, c["dp"]) for r in found)
        out.append((f"roots rounded to {c['dp']} dp = {c['expected']}", got == sorted(c["expected"])))
    elif t == "round_expr":
        x = Symbol(c["var"])
        eq = expand(num(c["lhs"]) - num(c["rhs"]))
        found = solve(eq, x)
        got = sorted(rnd_sf(r, c["sf"]) for r in found)
        out.append((f"roots rounded to {c['sf']} sf = {c['expected']}", got == sorted(c["expected"])))
        out.append(("rearranged form 2x^2+4x-15", simplify(eq - num("2*x**2+4*x-15")) == 0))
        d = discriminant(eq, x)
        out.append(("discriminant 136 (non-square)", d == 136))
    elif t == "cts":
        x = Symbol(c["var"])
        out.append(("completed-square form expands to expression", expand(num(c["expr"]) - num(c["form"])) == 0))
        if "solutions" in c:
            sols = [num(s) for s in c["solutions"]]
            out.append(("stated surd roots are roots", all(simplify(num(c["expr"]).subs(x, s)) == 0 for s in sols)))
            out.append(("sympy roots equal stated", roots_close(solve(num(c["expr"]), x), sols)))
        if "min_point" in c:
            e = num(c["expr"])
            mp = [num(v) for v in c["min_point"]]
            out.append(("minimum point (x)", solve(e.diff(x), x) == [mp[0]]))
            out.append(("minimum value (y)", simplify(e.subs(x, mp[0]) - mp[1]) == 0))
            out.append(("leading coefficient positive (minimum)", Poly(e, x).LC() > 0))
    elif t == "rectangle":
        w = Symbol("w")
        length = num(c["len_expr"])
        area = num(c["area"])
        eq = expand(w * length - area)
        out.append(("shown equation 2w^2+3w-77 = 0", simplify(eq - num("2*w**2+3*w-77")) == 0))
        sol = solve(eq, w)
        pos = [r for r in sol if r > 0]
        out.append(("exactly one positive root", len(pos) == 1))
        out.append(("positive root = 11/2", pos and pos[0] == num(c["expected_w"])))
        out.append(("perimeter = 39", pos and 2 * (pos[0] + length.subs(w, pos[0])) == num(c["expected_perimeter"])))
        out.append(("discriminant 625 = 25^2", discriminant(eq, w) == 625))
    elif t == "pythag":
        x = Symbol("x")
        eq = expand(num(c["short"]) ** 2 + num(c["other"]) ** 2 - num(c["hyp"]) ** 2)
        out.append(("shown equation 2x^2+4x-77 = 0", simplify(eq - num(c["target_poly"])) == 0))
        pos = [r for r in solve(eq, x) if N(r) > 0]
        out.append(("one positive root", len(pos) == 1))
        out.append(("x to 3 sf", rnd_sf(pos[0], 3) == c["expected_x_sf3"]))
        short, other = pos[0], pos[0] + 2
        out.append(("Pythagoras holds exactly for exact root", simplify(short**2 + other**2 - 81) == 0))
        out.append(("discriminant 632 (non-square)", discriminant(eq, x) == 632))
    elif t == "ball":
        t_ = Symbol(c["var"])
        p = num(c["poly"])
        sols = solve(p, t_)
        pos = [r for r in sols if N(r) > 0]
        out.append(("one positive root", len(pos) == 1))
        out.append(("t to 2 dp", rnd_dp(pos[0], 2) == c["expected_t"]))
        neg = [r for r in sols if N(r) < 0]
        out.append(("other root negative (rejection valid)", len(neg) == 1))
        out.append(("height at root is zero", simplify(p.subs(t_, pos[0])) == 0))
    elif t == "positive":
        x = Symbol(c["var"])
        e = num(c["expr"])
        out.append(("completed-square form expands to expression", expand(e - num(c["form"])) == 0))
        out.append(("minimum value equals 1", minimum(e, x) == num(c["min_value"])))
        out.append(("no real roots (disc < 0)", discriminant(e, x) < 0))
    else:
        out.append(("known check type", False))
    return out

def main(path):
    qs = json.load(open(path))
    results = []
    total = 0
    for q in qs:
        total += q["marks"]
        checks = check(q)
        results.append({"id": q["id"], "marks": q["marks"],
                        "checks": [{"name": n, "pass": bool(v)} for n, v in checks],
                        "all_pass": all(bool(v) for _, v in checks)})
    json.dump({"total_marks": total, "results": results}, sys.stdout, indent=2)

if __name__ == "__main__":
    main(sys.argv[1])
