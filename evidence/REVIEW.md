# Reviewer quick path

Start here to review this contract in the shortest time.

1. Read the README for what the contract is, the lifecycle, and the live verification summary.
2. Read `contracts/prediction_market.py` (single file). The money rules are in the header docstring: integer microGEN, 2% settlement fee, winners split 98% of the pool pro-rata.
3. Check the deployment record in `evidence/DEPLOYMENT.md`: contract address, deploy transaction, deployed source commit and SHA256.
4. Check `evidence/live-verification.json`: every core transaction with its FINALIZED receipt, and the final read-back of all markets, balances and the platform pool.
5. Re-run the local tests (no network, LLM mocked):
   ```bash
   pip install -r requirements.txt
   python -m pytest tests/ -q
   ```
6. Re-run the live verification end to end (deploys a fresh contract; do not run it against the deployed address unless you want a second deployment):
   ```bash
   python3 scripts/verify_studionet.py
   ```
   To read back the deployed contract without sending transactions, use `genlayer-py` read_contract calls against the address in `evidence/DEPLOYMENT.md` (views: `get_market`, `get_bet`, `get_balance`, `get_platform_pool`, `get_odds`, `get_position`, `get_next_market_id`).
