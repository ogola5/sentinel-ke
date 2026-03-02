#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def _merge_base(base_ref: str, head_ref: str) -> str:
    return _run(["git", "merge-base", base_ref, head_ref])


def _changed_files(base: str, head: str) -> list[str]:
    out = _run(["git", "diff", "--name-only", f"{base}...{head}"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def _churn(base: str, head: str) -> tuple[int, int]:
    out = _run(["git", "diff", "--numstat", f"{base}...{head}"])
    added = 0
    deleted = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a, d = parts[0], parts[1]
        if a.isdigit():
            added += int(a)
        if d.isdigit():
            deleted += int(d)
    return added, deleted


@dataclass
class GuardrailResult:
    ok: bool
    failures: list[str]
    warnings: list[str]
    summary: dict[str, object]


def evaluate(
    *,
    changed_files: list[str],
    added: int,
    deleted: int,
    max_churn: int,
    max_files: int,
    test_threshold: int,
) -> GuardrailResult:
    failures: list[str] = []
    warnings: list[str] = []

    churn = added + deleted
    file_count = len(changed_files)

    plan_changed = any(
        p.startswith("docs/plans/") and not p.endswith("_TEMPLATE.md")
        for p in changed_files
    )
    backend_touched = any(p.startswith("backend/app/") for p in changed_files)
    frontend_touched = any(p.startswith("frontend/src/") for p in changed_files)
    tests_changed = any(
        p.startswith("backend/tests/") or p.startswith("frontend/src/__tests__/")
        for p in changed_files
    )
    docs_only = all(
        p.startswith("docs/") or p.startswith(".github/") for p in changed_files
    ) if changed_files else False

    if not docs_only and churn > max_churn and not plan_changed:
        failures.append(
            f"Large churn detected ({churn} lines) without a plan doc change under docs/plans/."
        )

    if not docs_only and file_count > max_files and not plan_changed:
        failures.append(
            f"Large file span detected ({file_count} files) without a plan doc update."
        )

    if (backend_touched or frontend_touched) and churn > test_threshold and not tests_changed:
        failures.append(
            f"Code changed with {churn} lines but no test file updates detected."
        )

    if churn > (max_churn * 2):
        warnings.append(
            "Very high churn detected; strongly consider splitting the PR into smaller, reviewable slices."
        )

    summary = {
        "files_changed": file_count,
        "lines_added": added,
        "lines_deleted": deleted,
        "line_churn": churn,
        "plan_changed": plan_changed,
        "tests_changed": tests_changed,
        "backend_touched": backend_touched,
        "frontend_touched": frontend_touched,
        "docs_only": docs_only,
    }

    return GuardrailResult(
        ok=len(failures) == 0,
        failures=failures,
        warnings=warnings,
        summary=summary,
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PR planning + churn guardrails")
    p.add_argument("--base-ref", required=True, help="Base ref, e.g. origin/main")
    p.add_argument("--head-ref", default="HEAD", help="Head ref (default HEAD)")
    p.add_argument("--max-churn", type=int, default=1600)
    p.add_argument("--max-files", type=int, default=60)
    p.add_argument("--test-threshold", type=int, default=300)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    try:
        base_sha = _merge_base(args.base_ref, args.head_ref)
    except subprocess.CalledProcessError as exc:
        print(f"[guardrails][error] could not compute merge-base: {exc}", file=sys.stderr)
        return 2

    files = _changed_files(base_sha, args.head_ref)
    added, deleted = _churn(base_sha, args.head_ref)
    result = evaluate(
        changed_files=files,
        added=added,
        deleted=deleted,
        max_churn=max(1, int(args.max_churn)),
        max_files=max(1, int(args.max_files)),
        test_threshold=max(1, int(args.test_threshold)),
    )

    print("[guardrails][summary]")
    print(json.dumps(result.summary, indent=2, sort_keys=True))

    for w in result.warnings:
        print(f"[guardrails][warn] {w}")
    for f in result.failures:
        print(f"[guardrails][fail] {f}")

    if result.ok:
        print("[guardrails][ok] PR guardrails passed")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
