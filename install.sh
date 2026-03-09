#!/usr/bin/env bash
# ARES Installation Script
# Run: bash install.sh

set -e

echo "======================================"
echo "  ARES — Installation"
echo "======================================"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3.11+ required. Install via: brew install python@3.11"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python: $PYTHON_VERSION"

# Check pip
if ! command -v pip3 &>/dev/null; then
    echo "ERROR: pip3 not found."
    exit 1
fi

# Install in editable mode
echo ""
echo "Installing ARES..."
pip3 install -e ".[screen]" 2>/dev/null || pip3 install -e .

echo ""
echo "Initializing ARES directories..."
ares init

echo ""
echo "======================================"
echo "  Installation complete."
echo "======================================"
echo ""
echo "Next steps:"
echo "  1. Set your Anthropic API key:"
echo "     export ANTHROPIC_API_KEY=sk-ant-..."
echo "     (add to ~/.zshrc or ~/.bash_profile)"
echo ""
echo "  2. Run first-time setup:"
echo "     ares setup"
echo ""
echo "  3. Start the daemon:"
echo "     ares start"
echo ""
echo "  4. Give ARES a goal:"
echo '     ares goal "make a YouTube video about productivity hacks"'
echo ""
