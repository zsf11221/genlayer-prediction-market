# Known limitations

Scope and range statements for this contract. These describe what the contract does and does not cover.

- Nominal TEST units. All GEN in this contract is a nominal in-contract TEST ledger (`claim_test_gen` credits 1,000 GEN once per address). Bets, payouts, refunds and fees move ledger entries only; no real GEN is transferred by this contract.
- Settlement verdicts judge evidence sufficiency. Adjudication decides whether the attached evidence credibly establishes an outcome under the market's written settlement criteria and names a deciding source. Verdicts are consensus judgments about the submitted evidence, not independent fact-finding.
- No wall-clock deadlines. The contract has no clock source. Betting ends only when someone proposes an outcome; settlement happens only when someone calls settle after a verdict.
- Single-contract primitive. There is no frontend. Calls are made with the GenLayer CLI or `genlayer-py`; see `scripts/verify_studionet.py` for the full call sequence.
- Script accounts only. The live run used temporary script-generated accounts. The browser-wallet signing path was not exercised in this run.
- LLM verdicts are consensus decisions. Settlement verdicts are produced by validators independently running the same prompt on the same stored evidence and agreeing on a canonical `OUTCOME|<index>` or `INVALID` string. They are judgments about whether the evidence meets the written criteria, not deterministic measurements.
- Explorer availability. The network's explorer address page is linked from the README; the on-chain record is verifiable through the Studio RPC (`eth_getTransactionReceipt`, contract reads) as documented in `live-verification.json`.
- Runner version. The contract pins runner `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`.
