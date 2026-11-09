# ⚡ Lean Parallel SDLC Harness v3 (Windows + macOS + Linux)

A 100% cross-platform, token-optimized multi-agent SDLC harness for **Claude Code** and **Antigravity**.

## Windows, macOS & Linux Installation

### Option A: Windows (PowerShell or CMD — No Admin Rights Required)
```powershell
# In PowerShell:
.\install.ps1

# Or in Command Prompt (CMD):
install.bat

# Or directly via Python on any OS:
python install.py
```

### Option B: macOS / Linux / WSL / Git Bash
```bash
./install.sh
```

## Running the Dashboard & Harness on Windows
```powershell
# 1. Start the Live Mission Control Dashboard
python dashboard.py --port 8765
# Open http://localhost:8765

# 2. Run Visual Demo (0 API Tokens)
python harness.py --demo

# 3. Process all files in requirements\inbox\
python harness.py --from-folder

# 4. Watch requirements\inbox\ continuously
python harness.py --watch

# 5. Sync latest skills from ECC repo (cross-platform Python)
python sync_ecc_skills.py
```
