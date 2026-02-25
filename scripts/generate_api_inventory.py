#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RouteRow:
    method: str
    path: str
    tag: str
    module: str
    function: str


def _resolve_target_files(root: Path) -> list[Path]:
    registry = root / "backend" / "app" / "api" / "router_registry.py"
    src = registry.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(registry))

    alias_to_module: dict[str, str] = {}
    mounted_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for imported in node.names:
                if imported.name == "router":
                    alias_to_module[imported.asname or imported.name] = node.module
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "RouterMount":
            if node.args and isinstance(node.args[0], ast.Name):
                mounted_aliases.add(node.args[0].id)

    out: list[Path] = []
    for alias in sorted(mounted_aliases):
        module = alias_to_module.get(alias)
        if not module or not module.startswith("app."):
            continue
        rel = module.split(".", 1)[1]
        module_file = (root / "backend" / "app" / Path(*rel.split("."))).with_suffix(".py")
        if module_file.exists():
            out.append(module_file)
    return out


def _extract_router_meta(tree: ast.AST) -> tuple[str, str]:
    prefix = ""
    tag = ""

    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "router" for t in node.targets):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        if not isinstance(call.func, ast.Name) or call.func.id != "APIRouter":
            continue

        for kw in call.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                prefix = kw.value.value
            if kw.arg == "tags" and isinstance(kw.value, ast.List) and kw.value.elts:
                first = kw.value.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    tag = first.value

    return prefix, tag


def _collect_routes(py_file: Path, repo_root: Path) -> list[RouteRow]:
    src = py_file.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(py_file))
    prefix, tag = _extract_router_meta(tree)

    module = str(py_file.relative_to(repo_root)).replace("/", ".")
    if module.endswith(".py"):
        module = module[:-3]

    rows: list[RouteRow] = []
    function_nodes = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, function_nodes):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if not isinstance(dec.func.value, ast.Name) or dec.func.value.id != "router":
                continue
            method = dec.func.attr.lower()
            if method not in {"get", "post", "put", "delete", "patch", "head", "options"}:
                continue
            if not dec.args:
                continue
            arg0 = dec.args[0]
            if not isinstance(arg0, ast.Constant) or not isinstance(arg0.value, str):
                continue
            rows.append(
                RouteRow(
                    method=method.upper(),
                    path=f"{prefix}{arg0.value}",
                    tag=tag or "(none)",
                    module=module,
                    function=node.name,
                )
            )
    return rows


def _collect_main_routes(main_file: Path, repo_root: Path) -> list[RouteRow]:
    src = main_file.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(main_file))
    module = str(main_file.relative_to(repo_root)).replace("/", ".")
    if module.endswith(".py"):
        module = module[:-3]

    rows: list[RouteRow] = []
    function_nodes = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, function_nodes):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if not isinstance(dec.func.value, ast.Name) or dec.func.value.id != "app":
                continue
            method = dec.func.attr.lower()
            if method not in {"get", "post", "put", "delete", "patch", "head", "options"}:
                continue
            if not dec.args or not isinstance(dec.args[0], ast.Constant) or not isinstance(dec.args[0].value, str):
                continue

            tag = "(none)"
            for kw in dec.keywords:
                if kw.arg == "tags" and isinstance(kw.value, ast.List) and kw.value.elts:
                    first = kw.value.elts[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        tag = first.value

            rows.append(
                RouteRow(
                    method=method.upper(),
                    path=dec.args[0].value,
                    tag=tag,
                    module=module,
                    function=node.name,
                )
            )
    return rows


def _render(rows: list[RouteRow]) -> str:
    out = []
    out.append("# API Endpoint Inventory")
    out.append("")
    out.append("Auto-generated from FastAPI routers. Do not edit manually.")
    out.append("")
    out.append("Regenerate with:")
    out.append("")
    out.append("```bash")
    out.append("python3 scripts/generate_api_inventory.py --write")
    out.append("```")
    out.append("")
    out.append("| Method | Path | Tag | Handler |")
    out.append("|---|---|---|---|")
    for r in rows:
        handler = f"`{r.module}:{r.function}`"
        out.append(f"| `{r.method}` | `{r.path}` | `{r.tag}` | {handler} |")
    out.append("")
    return "\n".join(out)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate API endpoint inventory markdown")
    parser.add_argument("--check", action="store_true", help="exit non-zero when docs file is not up-to-date")
    parser.add_argument("--write", action="store_true", help="write docs/API_ENDPOINT_INVENTORY.md (default mode)")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = Path(__file__).resolve().parent.parent

    targets = _resolve_target_files(root)
    if not targets:
        print("failed to resolve mounted router files from backend/app/api/router_registry.py")
        return 1

    rows: list[RouteRow] = []
    for file_path in targets:
        rows.extend(_collect_routes(file_path, repo_root=root))
    rows.extend(_collect_main_routes(root / "backend" / "app" / "main.py", repo_root=root))

    rows.sort(key=lambda x: (x.path, x.method, x.module, x.function))

    content = _render(rows)
    out_file = root / "docs" / "API_ENDPOINT_INVENTORY.md"
    existing = out_file.read_text(encoding="utf-8") if out_file.exists() else ""

    if args.check:
        if existing != content:
            print(f"stale {out_file}; run: python3 scripts/generate_api_inventory.py --write")
            return 1
        print(f"inventory up-to-date ({len(rows)} endpoints)")
        return 0

    if args.write or not args.check:
        out_file.write_text(content, encoding="utf-8")
        print(f"wrote {out_file} ({len(rows)} endpoints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
