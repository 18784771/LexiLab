from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from lexilab.config.settings import load_settings
from lexilab.context import AppContext
from rapidfuzz.distance import DamerauLevenshtein


def top_by_frequency(rows: list[dict], limit: int) -> list[str]:
    def key(row: dict) -> tuple:
        rank = row.get("frq") or row.get("bnc") or 10**9
        return (int(rank), int(row.get("rank") or 10**9), row["word_key"])

    return [row["word_key"] for row in sorted(rows, key=key)[:limit]]


def metrics(ctx: AppContext, words: list[str], all_rows: dict[str, dict], learned: set[str]) -> dict:
    similar_pairs = 0
    for index, left in enumerate(words):
        for right in words[index + 1 :]:
            if DamerauLevenshtein.normalized_similarity(left, right) >= 0.8:
                similar_pairs += 1
    relations = ctx.vocab_repo.relations_for_sources(set(words))
    selected = set(words)
    synonym_pairs = sum(
        1
        for row in relations
        if row["relation_type"] == "synonym"
        and row["source_word"] in selected
        and row["target_word"] in selected
    )
    learned_related = ctx.vocab_repo.relations_for_sources(learned)
    related_to_learned = {
        row["target_word"]
        for row in learned_related
        if row["target_word"] in selected
    }
    freqs = [int(all_rows[w].get("frq") or 10**9) for w in words]
    pos = [str((ctx.vocab_repo.word_metadata(w) or {}).get("pos") or "") for w in words]
    return {
        "top1000_frequency_words": sum(1 for value in freqs if value <= 1000),
        "median_frequency_rank": sorted(freqs)[len(freqs) // 2] if freqs else None,
        "spelling_pairs_ge_080": similar_pairs,
        "synonym_pairs_in_batch": synonym_pairs,
        "related_to_learned": len(related_to_learned),
        "pos_categories": len({p for p in pos if p}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", type=Path, default=Path("reports/relation_acceptance.json"))
    args = parser.parse_args()

    settings = load_settings()
    settings.audio.enabled = False
    ctx = AppContext(settings)
    book = ctx.active_book()
    exclude = ctx.repo.learned_keys() | ctx.repo.screening_known_keys()
    rows = [row for row in ctx.vocab_repo.new_word_rows(book) if row["word_key"] not in exclude]
    all_rows = {row["word_key"]: row for row in rows}
    learned = ctx.repo.learned_keys()

    alphabetical = [key for key in ctx.vocab_repo.book_word_keys(book) if key not in exclude][
        : args.limit
    ]
    random_keys = [row["word_key"] for row in rows]
    random.Random(20261114).shuffle(random_keys)
    random_keys = random_keys[: args.limit]
    frequency = top_by_frequency(rows, args.limit)
    smart_items = ctx.planner.orderer.choose(book, args.limit, exclude, order="smart")
    smart = [item.word_key for item in smart_items]

    result = {
        "book": book,
        "candidate_count": len(rows),
        "learned_count": len(learned),
        "limit": args.limit,
        "strategies": {
            "A_alphabetical": {
                "words": alphabetical,
                "metrics": metrics(ctx, alphabetical, all_rows, learned),
            },
            "B_random": {
                "words": random_keys,
                "metrics": metrics(ctx, random_keys, all_rows, learned),
            },
            "C_frequency": {
                "words": frequency,
                "metrics": metrics(ctx, frequency, all_rows, learned),
            },
            "D_smart": {
                "words": smart,
                "metrics": metrics(ctx, smart, all_rows, learned),
                "reasons": {item.word_key: item.reasons for item in smart_items},
            },
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["strategies"], ensure_ascii=False, indent=2)[:12000])
    print(f"written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
