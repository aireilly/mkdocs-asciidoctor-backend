# Get hacking

```cmd
# From project root
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e .[dev]

# In ~/mkdocs-asciidoctor-backend (with this venv active)
python -m pip install -U mkdocs-material
python -m mkdocs --version

# Run a build
python -m mkdocs build -f demo/mkdocs.yml -v \
&& python -m mkdocs serve -f demo/mkdocs.yml

# Package
python -m pip install --upgrade build twine
rm -rf dist/ build/ *.egg-info
python -m build
twine check dist/*

git tag v0.0.1
git push origin --tags

# Go forth
pip install mkdocs-asciidoctor-backend --upgrade
```

Demo build: https://aireilly.github.io/mkdocs-asciidoctor-backend/