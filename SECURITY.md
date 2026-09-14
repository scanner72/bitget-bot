# Security Policy

The Bitget Divergent Agent Desk team takes financial security and credential isolation with extreme seriousness.

---

## 🔒 Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

---

## 🛡️ Security Best Practices for Trading Bot Deployments

1. **API Key Isolation**:
   - **Never enable withdrawal permissions** on Bitget API keys.
   - Use **Demo Trading API keys** (`paptrading`) during testing and evaluation.
   - Bind API keys to specific static server IP addresses whenever possible.
2. **Environment Protection**:
   - Never commit `.env` containing API secrets to source control.
   - The `.gitignore` file enforces exclusion of all `.env*` files except `.env.example`.
3. **Network Security**:
   - Bind the FastAPI dashboard (`HOST=127.0.0.1`) unless shielded behind an authenticated HTTPS reverse proxy.

---

## 🚨 Reporting a Vulnerability

Please report vulnerabilities privately via GitHub Private Vulnerability Reporting or by emailing `security@bitget-desk.dev`.
