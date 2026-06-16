#!/bin/sh
# Install the pre-commit secret scanner into this clone's .git/hooks.
root="$(git rev-parse --show-toplevel)"
cat > "$root/.git/hooks/pre-commit" <<'HOOK'
#!/bin/sh
root="$(git rev-parse --show-toplevel)"
py="$root/venv/bin/python"; [ -x "$py" ] || py="python3"
exec "$py" "$root/scripts/secret_scan.py"
HOOK
chmod +x "$root/.git/hooks/pre-commit"
echo "pre-commit secret scanner installed."
