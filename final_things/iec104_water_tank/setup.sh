#!/bin/bash
# Setup script for IEC-104 Water Tank Simulation

echo "=========================================="
echo "IEC-104 Water Tank Simulation - Setup"
echo "=========================================="
echo ""

# Change to script directory
cd "$(dirname "$0")"

# Check Python version
echo "Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "[-] Python 3 is not installed!"
    echo "Please install Python 3.8 or higher"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "[+] Found Python $PYTHON_VERSION"
echo ""

# Create virtual environment
echo "Creating virtual environment..."
if [ -d "venv" ]; then
    echo "[!]  Virtual environment already exists, skipping..."
else
    python3 -m venv venv
    echo "[+] Virtual environment created"
fi
echo ""

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate
echo "[+] Virtual environment activated"
echo ""

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip -q
echo "[+] pip upgraded"
echo ""

# Install dependencies
echo "Installing dependencies..."
echo "  - lib60870 (IEC-104 protocol library)"
pip install lib60870 -q
echo "[+] Dependencies installed"
echo ""

# Check tkinter
echo "Checking tkinter (GUI library)..."
if python3 -c "import tkinter" 2>/dev/null; then
    echo "[+] tkinter is available"
else
    echo "[!]  tkinter is not available!"
    echo ""
    echo "Please install tkinter for your system:"
    echo "  - macOS: brew install python-tk"
    echo "  - Ubuntu/Debian: sudo apt-get install python3-tk"
    echo "  - Fedora: sudo dnf install python3-tkinter"
    echo ""
fi
echo ""

# Make scripts executable
echo "Making scripts executable..."
chmod +x run_server.sh run_hmi.sh
echo "[+] Scripts are executable"
echo ""

# Done
echo "=========================================="
echo "[+] Setup Complete!"
echo "=========================================="
echo ""
echo "To start the system:"
echo ""
echo "1. Start the server:"
echo "   ./run_server.sh"
echo ""
echo "2. In a new terminal, start the HMI:"
echo "   ./run_hmi.sh"
echo ""
echo "For detailed instructions, see:"
echo "  - QUICKSTART.md (quick start guide)"
echo "  - README.md (full documentation)"
echo ""
