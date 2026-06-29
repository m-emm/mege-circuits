#! /bin/bash

PYTHON_FILES=()
while IFS= read -r -d "" file; do
    PYTHON_FILES+=("$file")
done < <(find src tests examples -name '*.py' -print0)

# Format code
if [ "${#PYTHON_FILES[@]}" -gt 0 ]; then
    isort "${PYTHON_FILES[@]}"
    black "${PYTHON_FILES[@]}"
fi

# # Format workflow files
# npx prettier --write  .github/workflows/*.yml

# Run linting (same as GitHub Actions)
echo "Running flake8 linting (syntax errors and undefined names only)..."
flake8 src/ tests/ examples/ --count --select=E9,F63,F7,F82 --ignore=F824,F401 --show-source --statistics
if [ $? -ne 0 ]; then
    echo "Syntax or undefined-name linting failed."
    exit 1
fi

echo "Checking for unused imports..."
flake8 --select=F401 --exclude="*/simple.py,build/*" src/ examples/ tests/
if [ $? -ne 0 ]; then
    echo "Found unused imports! Please remove them before committing."
    exit 1
fi
echo "No unused imports found."
