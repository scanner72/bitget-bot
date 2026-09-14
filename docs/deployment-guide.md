# 🚢 Production Deployment & Bitget Demo Setup Guide

This guide details configuring, hardening, and deploying the **Bitget S2 Divergent Agent Desk** on local workstations and remote Linux VPS servers.

---

## 1. System Requirements

| Component | Specification |
|:---|:---|
| **OS** | Linux (Ubuntu 22.04/24.04 LTS), macOS, Windows 10/11 (WSL2 / Native) |
| **Python** | Python 3.11 or 3.12 |
| **Docker** | Docker Engine 24+ & Docker Compose v2 (Optional for containerized run) |
| **RAM** | 2 GB minimum (4 GB recommended) |
| **Network** | Reliable internet connection with low latency to Bitget API (`api.bitget.com`) |

---

## 2. Bitget Universal Trading Account (UTA) Demo Setup

1. **Log in to Bitget**: Navigate to [Bitget.com](https://www.bitget.com).
2. **Switch to Demo Trading**: Open the Futures menu and select **Demo Trading** (`paptrading`).
3. **Generate API Key**:
   - Go to **Account ➔ API Management ➔ Create API Key**.
   - Select **Demo Trading API**.
   - Permissions: **Read-Only** and **Futures Trading**.
   - **NEVER** enable Withdrawal permissions!
   - Note down your `API Key`, `Secret Key`, and `Passphrase`.

---

## 3. Environment Configuration (`.env`)

Copy the template:
```bash
cp .env.example .env
```

Set the essential variables:
```env
# Execution Mode
EXEC_MODE=hub_demo
BITGET_DEMO=1
BITGET_ALLOW_LIVE=0

# Bitget Demo Credentials (Keep strictly local)
BITGET_API_KEY=your_demo_api_key_here
BITGET_API_SECRET=your_demo_secret_here
BITGET_PASSPHRASE=your_demo_passphrase_here

# Risk Guard
RISK_USD_PER_TRADE=2.0
MAX_NOTIONAL_USD=100.0
MIN_NOTIONAL_USD=10.0
MAX_DAILY_LOSS_USD=50.0
MAX_POSITIONS=8
COOLDOWN_SEC=900

# Dashboard
PORT=8080
HOST=0.0.0.0
```

---

## 4. One-Click Deployment

### Local Workstation (PowerShell / Bash)
```powershell
# Windows:
.\start.ps1

# Linux / macOS:
./start.sh
```

### Docker Compose
```bash
docker compose up -d --build
```
Access the web dashboard at **`http://localhost:8080`**.

### Remote Server Deployment over SSH
Deploy the entire platform to your remote cloud VPS with one command:
```powershell
# From Windows workstation:
.\deploy-remote.ps1 -RemoteHost "10.10.10.11" -RemoteUser "operator" -RemotePath "/opt/bitget-bot"
```
```bash
# From Linux / macOS workstation:
./deploy-remote.sh 10.10.10.11 operator /opt/bitget-bot
```
