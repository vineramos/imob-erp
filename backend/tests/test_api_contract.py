from app.main import app


def test_api_does_not_register_duplicate_method_path_pairs():
    seen: dict[tuple[str, str], str] = {}
    duplicates: list[str] = []

    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api"):
            continue
        methods = set(getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"}
        for method in methods:
            key = (method, path)
            name = getattr(route, "name", "<unnamed>")
            if key in seen:
                duplicates.append(f"{method} {path}: {seen[key]} x {name}")
            else:
                seen[key] = name

    assert not duplicates, "Rotas duplicadas encontradas:\n" + "\n".join(sorted(duplicates))
