# CryoQuant — Agent Context

Research-to-backtest quant pipeline (data → features → signals → backtests). See [README.md](README.md) for layout and quick start.

---

## Cursor Cloud specific instructions

- **Python:** 3.12 venv at `.venv/`. First-time VM bootstrap needs `sudo apt install python3.12-venv`.
- **Install:** `pip install -e ".[dev]"` then `pip install jinja2` (reports use Jinja2 but it is not yet declared in `pyproject.toml`).
- **Tests:** `python -m pytest tests/ -v` (live/slow tests deselected by default).
- **Options workflow:** set `export CRYOBACKTESTER_DATA_DIR=/workspace/repos/CryoBacktester/backtester/data` when CryoBacktester parquets are present.
- **Spot example script:** `python scripts/ema_cross_backtest.py` calls Binance REST — often returns HTTP 451 from cloud VMs (geo-restricted). Use unit tests or a synthetic in-process pipeline for offline smoke.
- **CLI:** `python -c "from cryoquant.cli import main; raise SystemExit(main(['catalog','list']))"` (no `__main__.py` under `cryoquant.cli` yet).
- **Cross-repo data:** default `CRYOBACKTESTER_DATA_DIR` in `config.py` points at a macOS dev path; override via env var in cloud.
