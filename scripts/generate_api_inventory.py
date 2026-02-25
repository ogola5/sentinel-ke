#!/usr/bin/env python3
from __future__ import annotations

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
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if not isinstance(dec.func.value, ast.Name) or dec.func.value.id != "router":
                continue
            method = dec.func.attr.lower()
            if method not in {"get", "post", "put", "delete", "patch"}:
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


def _render(rows: list[RouteRow]) -> str:
    out = []
    out.append("# API Endpoint Inventory")
    out.append("")
    out.append("Auto-generated from FastAPI routers. Do not edit manually.")
    out.append("")
    out.append("Regenerate with:")
    out.append("")
    out.append("```bash")
    out.append("python3 scripts/generate_api_inventory.py")
    out.append("```")
    out.append("")
    out.append("| Method | Path | Tag | Handler |")
    out.append("|---|---|---|---|")
    for r in rows:
        handler = f"`{r.module}:{r.function}`"
        out.append(f"| `{r.method}` | `{r.path}` | `{r.tag}` | {handler} |")
    out.append("")
    return "\n".join(out)


def main() -> int:
    root = Path(__file__).resolve().parent.parent

    targets = sorted((root / "backend" / "app" / "api").glob("*.py"))
    targets.append(root / "backend" / "app" / "cases" / "api.py")

    rows: list[RouteRow] = []
    for file_path in targets:
        rows.extend(_collect_routes(file_path, repo_root=root))

    rows.sort(key=lambda x: (x.path, x.method, x.module, x.function))

    content = _render(rows)
    out_file = root / "docs" / "API_ENDPOINT_INVENTORY.md"
    out_file.write_text(content, encoding="utf-8")

    print(f"wrote {out_file} ({len(rows)} endpoints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
