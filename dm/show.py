"""Terminal rendering for answers, so the audience can read probabilities at a glance."""

from __future__ import annotations

from typing import Any, Mapping


def bar(p: float, width: int = 24) -> str:
    n = round(p * width)
    return "█" * n + "·" * (width - n)


def show_answer(name: str, ans: Mapping[str, Any]) -> None:
    kind = ans["type"]
    if kind == "choice":
        print(f"  {name}: {ans['choice']}   (confidence {ans['confidence']:.2f})")
        for label, p in ans["probabilities"].items():
            mark = "←" if label == ans["choice"] else " "
            print(f"    {label:<12} {bar(p)} {p:5.1%} {mark}")
    elif kind == "score":
        legend = ans["legend"]
        print(f"  {name}: {ans['score']:.2f}   (confidence {ans['confidence']:.2f})")
        for level, p in ans["probabilities"].items():
            print(f"    {level} {legend[level]:<28} {bar(p)} {p:5.1%}")
    else:
        print(f"  {name}: {ans['noul']:.1%} true   {bar(ans['noul'])}")
