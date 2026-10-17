# Agent-Ready Checker 🤖🌐

**Agent-Ready Checker** is an open-source web tool designed to analyze and score websites based on their readiness for AI agents and Large Language Models (LLMs). It helps developers and SEO specialists evaluate their **GEO (Generative Engine Optimization)** strategy.

## 🚀 Features
- Checks for `llms.txt`, AI-specific `robots.txt` rules, `agent.json`, and `MCP` endpoints.
- Evaluates **11+ AI bots** (GPTBot, ClaudeBot, PerplexityBot, etc.).
- Gives a score from 0 to 100 based on GEO and Agent readiness.

## 💻 Tech Stack
Python 3.12, Flask, BeautifulSoup4, Requests.

## ⚙️ How to run locally
```bash
git clone https://github.com/artemkoach/agent-ready-checker.git
cd agent-ready-checker
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py