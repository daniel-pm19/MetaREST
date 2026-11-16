"""Puntúa un CSV de respuestas SUS (columnas participant,q1..q10[,t1_s..t5_s])."""

import csv
import statistics
import sys


def sus(row: dict) -> float:
    total = 0
    for i in range(1, 11):
        v = int(row[f"q{i}"])
        if not 1 <= v <= 5:
            raise ValueError(f"{row.get('participant')}: q{i}={v} fuera de 1–5")
        total += v - 1 if i % 2 else 5 - v
    return total * 2.5


def main(path: str) -> None:
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    scores = [sus(r) for r in rows]
    for r, s in zip(rows, scores, strict=True):
        print(f"{r['participant']}: {s:.1f}")
    if not scores:
        print("Sin respuestas.")
        return
    print(f"n={len(scores)}  media={statistics.mean(scores):.1f}  mediana={statistics.median(scores):.1f}  rango={min(scores):.1f}–{max(scores):.1f}")
    if len(scores) < 5:
        print("Aviso: el plan pide al menos 5 participantes.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "experiments/sus/responses.csv")
