"""Deploy PredictionMarket to Stable Studionet and verify the lifecycle live.

Ephemeral accounts are generated in memory only. Private keys are never
written to disk, logs, or the repository. Only addresses, transaction
hashes, and read-back state are recorded.

Run from the repository root:
    python3 scripts/verify_studionet.py

Output: evidence/live-verification.json (updated after every step).
Requires: genlayer-py, eth-account. Network: Stable Studionet (61999).
"""

import hashlib
import json
import sys
import time
from pathlib import Path

from eth_account import Account

from genlayer_py import create_client
from genlayer_py.chains import studionet
from genlayer_py.types.transactions import TransactionStatus

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "contracts" / "prediction_market.py"
EVIDENCE_PATH = ROOT / "evidence" / "live-verification.json"
RPC = "https://studio.genlayer.com/api"
CHAIN_ID = 61999

GEN = 1_000_000
WAIT_INTERVAL_MS = 5000
WAIT_RETRIES = 240  # 240 x 5s = up to 20 minutes per transaction

# --- Market 1: normal settlement -------------------------------------------
M1_QUESTION = "Which candidate won the 2024 US presidential election?"
M1_OUTCOMES = "Donald Trump|Kamala Harris|Other candidate"
M1_CRITERIA = (
    "The market settles on the candidate named as the winner in the attached "
    "evidence. The evidence must name the winner, the election year, and a "
    "deciding source."
)
M1_SOURCE = "Polymarket 2024 US presidential election contract settlement"
M1_EVIDENCE = (
    "The 2024 US presidential election was won by Donald Trump. Polymarket's "
    "largest binary contract, with over 3.3 billion dollars of notional volume, "
    "settled on Donald Trump as the winner, confirmed by the official election outcome."
)

# --- Market 2: dispute ------------------------------------------------------
M2_QUESTION = "What bond did Polymarket's UMA optimistic oracle require to dispute a proposed outcome?"
M2_OUTCOMES = "About $750|About $7,500|No bond required"
M2_CRITERIA = (
    "The market settles on the bond amount named in the attached evidence. "
    "The evidence must name the amount, the oracle, and a deciding source."
)
M2_SOURCE = "Polymarket UMA optimistic oracle dispute rules"
# The attached evidence establishes outcome 0, although the proposal claims 1.
M2_EVIDENCE = (
    "Polymarket's UMA optimistic oracle requires anyone proposing an outcome to "
    "post a bond of about $750. A dispute requires a matching bond of about $750, "
    "and if the second proposal is also disputed, UMA token holders vote. The "
    "deciding source is the UMA optimistic oracle rulebook."
)
M2_DISPUTE_EVIDENCE = "No bond is needed at all, trust me."

# --- Market 3: INVALID ------------------------------------------------------
M3_QUESTION = "Which candidate won the 2024 US presidential election?"
M3_OUTCOMES = "Donald Trump|Kamala Harris|Other candidate"
M3_CRITERIA = M1_CRITERIA
M3_SOURCE = M1_SOURCE
M3_EVIDENCE = (
    "Source A says Donald Trump won the 2024 US presidential election. Source B "
    "says Kamala Harris won the 2024 US presidential election. The two sources "
    "disagree and no deciding source is named."
)

# --- Market 4 fallback (INVALID, reworded) ---------------------------------
M4_QUESTION = M2_QUESTION
M4_OUTCOMES = M2_OUTCOMES
M4_CRITERIA = M2_CRITERIA
M4_SOURCE = M2_SOURCE
M4_EVIDENCE = (
    "One source says the dispute bond was about $750. Another source says it was "
    "about $7,500. The two sources disagree and no deciding source is named."
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def tx_hash_str(tx) -> str:
    if isinstance(tx, bytes):
        return "0x" + tx.hex()
    return str(tx)


def leader_execution_result(receipt: dict):
    try:
        return receipt["consensus_data"]["leader_receipt"][0]["execution_result"]
    except (KeyError, IndexError, TypeError):
        return None


def receipt_summary(receipt: dict) -> dict:
    return {
        "hash": receipt.get("hash") or receipt.get("tx_id"),
        "status": str(receipt.get("status_name") or receipt.get("status")),
        "execution_result": leader_execution_result(receipt),
        "contract_address": (receipt.get("data") or {}).get("contract_address"),
    }


class Runner:
    def __init__(self, contract_address: str | None = None):
        self.creator = Account.create()
        self.bettor_b = Account.create()
        self.bettor_c = Account.create()
        self.contract_address = contract_address
        self.evidence = {
            "network": "Stable Studionet",
            "chain_id": CHAIN_ID,
            "rpc": RPC,
            "contract_address": contract_address,
            "deploy_tx": None,
            "deploy_source_sha256": hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
            "accounts": {
                "creator": self.creator.address,
                "bettor_b": self.bettor_b.address,
                "bettor_c": self.bettor_c.address,
            },
            "steps": [],
            "final_readback": {},
            "notes": [],
        }
        self._save()

    def _save(self) -> None:
        EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVIDENCE_PATH.write_text(json.dumps(self.evidence, indent=2, sort_keys=False))

    def client_for(self, account):
        return create_client(chain=studionet, account=account, endpoint=RPC)

    def wait_finalized(self, client, tx_hash: str, label: str) -> dict:
        """Wait for FINALIZED, tolerating transient RPC failures (502s, bad
        gateway HTML, dropped connections). Retries the poll; never resends
        the transaction."""
        last_error = None
        for attempt in range(30):
            try:
                receipt = client.wait_for_transaction_receipt(
                    tx_hash,
                    status=TransactionStatus.FINALIZED,
                    interval=WAIT_INTERVAL_MS,
                    retries=12,  # 60s of polling per attempt
                )
                summary = receipt_summary(receipt)
                log(f"  -> {label}: status={summary['status']} execution={summary['execution_result']}")
                if summary["status"] != "FINALIZED":
                    raise RuntimeError(f"{label}: not FINALIZED: {summary}")
                if summary["execution_result"] != "SUCCESS":
                    raise RuntimeError(f"{label}: execution not SUCCESS: {json.dumps(receipt, default=str)[:2000]}")
                return summary
            except RuntimeError:
                raise
            except Exception as e:  # transient RPC failure: retry the poll
                last_error = e
                log(f"  !! {label}: RPC poll failed (attempt {attempt + 1}/30): {str(e)[:200]}; retrying in 10s")
                time.sleep(10)
        raise RuntimeError(f"{label}: receipt poll kept failing: {last_error}")

    def write(self, account, method: str, args, label: str) -> dict:
        client = self.client_for(account)
        tx = client.write_contract(
            self.contract_address, method, account=account, args=list(args)
        )
        tx_hash = tx_hash_str(tx)
        step = {"step": label, "method": method, "args": [str(a)[:120] for a in args],
                "tx_hash": tx_hash, "status": "SENT", "execution_result": None}
        self.evidence["steps"].append(step)
        self._save()
        summary = self.wait_finalized(client, tx_hash, label)
        step.update(summary)
        self._save()
        return summary

    def read(self, method: str, args=None):
        last_error = None
        for attempt in range(10):
            try:
                client = self.client_for(self.creator)
                return client.read_contract(self.contract_address, method, args=list(args or []))
            except Exception as e:
                last_error = e
                log(f"  !! read {method}: RPC failed (attempt {attempt + 1}/10): {str(e)[:200]}; retrying in 5s")
                time.sleep(5)
        raise RuntimeError(f"read {method} kept failing: {last_error}")

    def deploy(self) -> None:
        code = CONTRACT_PATH.read_bytes()
        client = self.client_for(self.creator)
        log("deploying contract...")
        tx = client.deploy_contract(code, account=self.creator)
        tx_hash = tx_hash_str(tx)
        summary = self.wait_finalized(client, tx_hash, "deploy")
        address = summary.get("contract_address")
        if not address:
            raise RuntimeError(f"deploy receipt has no contract address: {summary}")
        self.contract_address = address
        self.evidence["contract_address"] = address
        self.evidence["deploy_tx"] = tx_hash
        self.evidence["steps"].append(
            {"step": "deploy", "method": "__init__", "args": [],
             "tx_hash": tx_hash, **summary}
        )
        self._save()
        log(f"deployed at {address}")

    def bet(self, account, market_id: str, outcome: int, amount_gen: int, label: str):
        return self.write(account, "bet", [market_id, str(outcome), str(amount_gen * GEN)], label)

    def adjudicate_and_read(self, market_id: str, method: str, label: str) -> str:
        self.write(self.creator, method, [market_id], label)
        market = self.read("get_market", [market_id])
        return market["verdict"]

    def settle_and_read(self, market_id: str, label: str) -> dict:
        self.write(self.creator, "settle", [market_id], label)
        return self.read("get_market", [market_id])


def main() -> int:
    contract_address = None
    if len(sys.argv) > 2 and sys.argv[1] == "--contract-address":
        contract_address = sys.argv[2]
    runner = Runner(contract_address)
    log(f"creator:  {runner.creator.address}")
    log(f"bettor_b: {runner.bettor_b.address}")
    log(f"bettor_c: {runner.bettor_c.address}")

    if not runner.contract_address:
        runner.deploy()

    # Fund all three bettors with TEST GEN (nominal in-contract ledger).
    for account, label in [
        (runner.creator, "creator claim_test_gen"),
        (runner.bettor_b, "bettor_b claim_test_gen"),
        (runner.bettor_c, "bettor_c claim_test_gen"),
    ]:
        runner.write(account, "claim_test_gen", [], label)

    demos = {"normal_settled": False, "dispute_adjudicated": False, "invalid_refunded": False}

    # --- Market 1: normal settlement (expect OUTCOME|0) ---
    m1 = runner.read("get_next_market_id")
    runner.write(runner.creator, "create_market",
                 [M1_QUESTION, M1_OUTCOMES, M1_CRITERIA, M1_SOURCE], "market1: create_market")
    runner.bet(runner.creator, m1, 0, 60, "market1: bet creator 60 GEN on outcome 0")
    runner.bet(runner.bettor_b, m1, 1, 30, "market1: bet bettor_b 30 GEN on outcome 1")
    runner.bet(runner.bettor_c, m1, 2, 10, "market1: bet bettor_c 10 GEN on outcome 2")
    odds1 = runner.read("get_odds", [m1])
    log(f"market1 odds after bets: {odds1}")
    runner.evidence["notes"].append(f"market1 odds after bets: {odds1}")
    runner.write(runner.creator, "propose_outcome", [m1, "0", M1_EVIDENCE], "market1: propose_outcome 0")
    verdict1 = runner.adjudicate_and_read(m1, "adjudicate", "market1: adjudicate")
    log(f"market1 verdict: {verdict1}")
    settled1 = runner.settle_and_read(m1, "market1: settle")
    log(f"market1 settled: {settled1['status']}")
    if settled1["status"] == "SETTLED_PAID":
        demos["normal_settled"] = True
    elif settled1["status"] == "SETTLED_REFUNDED":
        demos["invalid_refunded"] = True
    runner.evidence["notes"].append(
        f"market1: verdict {verdict1}, settled {settled1['status']}, "
        f"pool was 100 GEN, outcome totals {settled1['outcome_totals']}."
    )

    # --- Market 2: wrong proposal, then dispute ---
    m2 = runner.read("get_next_market_id")
    runner.write(runner.creator, "create_market",
                 [M2_QUESTION, M2_OUTCOMES, M2_CRITERIA, M2_SOURCE], "market2: create_market")
    runner.bet(runner.creator, m2, 0, 20, "market2: bet creator 20 GEN on outcome 0")
    runner.bet(runner.bettor_b, m2, 1, 20, "market2: bet bettor_b 20 GEN on outcome 1")
    runner.bet(runner.bettor_c, m2, 2, 20, "market2: bet bettor_c 20 GEN on outcome 2")
    runner.write(runner.creator, "propose_outcome", [m2, "1", M2_EVIDENCE],
                 "market2: propose_outcome 1 (evidence establishes 0)")
    verdict2 = runner.adjudicate_and_read(m2, "adjudicate", "market2: adjudicate")
    log(f"market2 verdict: {verdict2}")
    runner.write(runner.creator, "dispute", [m2, "2", M2_DISPUTE_EVIDENCE], "market2: dispute claims 2")
    verdict2b = runner.adjudicate_and_read(m2, "adjudicate_dispute", "market2: adjudicate_dispute")
    log(f"market2 dispute verdict: {verdict2b}")
    demos["dispute_adjudicated"] = True
    settled2 = runner.settle_and_read(m2, "market2: settle")
    log(f"market2 settled: {settled2['status']}")
    if settled2["status"] == "SETTLED_PAID":
        demos["normal_settled"] = True
    elif settled2["status"] == "SETTLED_REFUNDED":
        demos["invalid_refunded"] = True
    runner.evidence["notes"].append(
        f"market2: first verdict {verdict2}, dispute verdict {verdict2b}, "
        f"settled {settled2['status']}, pool was 60 GEN."
    )

    # --- Market 3: INVALID verdict, full refund ---
    m3 = runner.read("get_next_market_id")
    runner.write(runner.creator, "create_market",
                 [M3_QUESTION, M3_OUTCOMES, M3_CRITERIA, M3_SOURCE], "market3: create_market")
    runner.bet(runner.creator, m3, 0, 10, "market3: bet creator 10 GEN on outcome 0")
    runner.bet(runner.bettor_b, m3, 1, 10, "market3: bet bettor_b 10 GEN on outcome 1")
    runner.bet(runner.bettor_c, m3, 2, 10, "market3: bet bettor_c 10 GEN on outcome 2")
    runner.write(runner.creator, "propose_outcome", [m3, "0", M3_EVIDENCE],
                 "market3: propose_outcome 0 (contradictory evidence)")
    verdict3 = runner.adjudicate_and_read(m3, "adjudicate", "market3: adjudicate")
    log(f"market3 verdict: {verdict3}")
    settled3 = runner.settle_and_read(m3, "market3: settle")
    log(f"market3 settled: {settled3['status']}")
    if settled3["status"] == "SETTLED_REFUNDED":
        demos["invalid_refunded"] = True
    elif settled3["status"] == "SETTLED_PAID":
        demos["normal_settled"] = True
    runner.evidence["notes"].append(
        f"market3: verdict {verdict3}, settled {settled3['status']}, pool was 30 GEN."
    )

    # --- Fallback market 4 if the INVALID demo is still missing ---
    if not demos["invalid_refunded"]:
        runner.evidence["notes"].append("INVALID demo missing after market3; running fallback market4.")
        m4 = runner.read("get_next_market_id")
        runner.write(runner.creator, "create_market",
                     [M4_QUESTION, M4_OUTCOMES, M4_CRITERIA, M4_SOURCE], "market4: create_market")
        runner.bet(runner.creator, m4, 0, 10, "market4: bet creator 10 GEN on outcome 0")
        runner.bet(runner.bettor_b, m4, 1, 10, "market4: bet bettor_b 10 GEN on outcome 1")
        runner.bet(runner.bettor_c, m4, 2, 10, "market4: bet bettor_c 10 GEN on outcome 2")
        runner.write(runner.creator, "propose_outcome", [m4, "0", M4_EVIDENCE],
                     "market4: propose_outcome 0 (contradictory evidence)")
        verdict4 = runner.adjudicate_and_read(m4, "adjudicate", "market4: adjudicate")
        log(f"market4 verdict: {verdict4}")
        settled4 = runner.settle_and_read(m4, "market4: settle")
        log(f"market4 settled: {settled4['status']}")
        if settled4["status"] == "SETTLED_REFUNDED":
            demos["invalid_refunded"] = True
        runner.evidence["notes"].append(
            f"market4: verdict {verdict4}, settled {settled4['status']}, pool was 30 GEN."
        )

    # --- Final read-back (no new transactions) ---
    final = {
        "markets": {},
        "platform_pool_microgen": runner.read("get_platform_pool"),
        "creator_balance_microgen": runner.read("get_balance", [runner.creator.address]),
        "bettor_b_balance_microgen": runner.read("get_balance", [runner.bettor_b.address]),
        "bettor_c_balance_microgen": runner.read("get_balance", [runner.bettor_c.address]),
        "demos": demos,
        "readback_method": (
            "genlayer-py read_contract calls against Stable Studionet after all "
            "transactions reached FINALIZED; no new transactions were sent for the read-back."
        ),
    }
    for mid in ["1", "2", "3", "4"]:
        try:
            final["markets"][mid] = runner.read("get_market", [mid])
        except Exception as e:  # market may not exist
            log(f"get_market {mid}: {e}")
    runner.evidence["final_readback"] = final
    runner.evidence["notes"].append(f"demos demonstrated: {demos}")
    runner._save()
    log("DONE")
    log(json.dumps(final, indent=2)[:4000])
    if not all(demos.values()):
        log(f"WARNING: not all demos were demonstrated: {demos}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
