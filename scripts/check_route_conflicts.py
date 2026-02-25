#!/usr/bin/env python3
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RouteDef:
    method: str
    full_path: str
    file_path: str
    function_name: str


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


def _extract_prefix(tree: ast.AST) -> str:
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
                return kw.value.value
    return ""


def _collect_routes(file_path: Path) -> list[RouteDef]:
    try:
        src = file_path.read_text(encoding="utf-8")
    except Exception:
        return []

    try:
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError as exc:
        print(f"[route-check][fail] syntax error in {file_path}: {exc}")
        return []

    prefix = _extract_prefix(tree)
    out: list[RouteDef] = []

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
            first = dec.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            route = first.value
            out.append(
                RouteDef(
                    method=method.upper(),
                    full_path=f"{prefix}{route}",
                    file_path=str(file_path),
                    function_name=node.name,
                )
            )
    return out


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    targets = _resolve_target_files(root)
    if not targets:
        print("[route-check][fail] unable to resolve mounted router files from router_registry.py")
        return 1

    all_routes: dict[tuple[str, str], list[RouteDef]] = {}
    for fp in targets:
        for route in _collect_routes(fp):
            key = (route.method, route.full_path)
            all_routes.setdefault(key, []).append(route)

    dupes = {k: v for k, v in all_routes.items() if len(v) > 1}
    if not dupes:
        print("[route-check][ok] no duplicate method+path routes found")
        return 0

    print("[route-check][fail] duplicate routes found:")
    for (method, path), defs in sorted(dupes.items()):
        print(f"  - {method} {path}")
        for d in defs:
            print(f"    {d.file_path}:{d.function_name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
