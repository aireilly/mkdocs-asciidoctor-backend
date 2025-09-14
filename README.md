# Getting started

* Each .adoc file spawns an asciidoctor subprocess
* BeautifulSoup processes every file (though optimized to single pass)
* Memory usage: ThreadPoolExecutor keeps rendered content in memory during build
* Intelligent caching prevents unnecessary re-renders
* Configurable worker limits `max_workers: 8` prevents resource exhaustion (is this actually useful?)
* Per-build memoization avoids duplicate processing

```cmd
# From project root
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e .[dev]

# In ~/mkdocs-asciidoctor-backend (with this venv active)
python -m pip install -U mkdocs-material
python -m mkdocs --version

# Run a build
python -m mkdocs build -f demo/mkdocs.yml -v \
&& python -m mkdocs serve -f demo/mkdocs.yml
```

