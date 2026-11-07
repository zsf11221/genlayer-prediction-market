# Deployment record

- Network: Stable Studionet (Chain ID 61999)
- RPC: https://studio.genlayer.com/api
- Contract: `0xEedB8c6f3d3aa7b736f226c5E1B7d5D633e077FA`
- Explorer: https://explorer-studio.genlayer.com/address/0xEedB8c6f3d3aa7b736f226c5E1B7d5D633e077FA
- Deploy transaction: `0xb05c47fb634ea15f12882619b174b1a510916b0e8f557dd883473020a017d282`
- Deployed source: `contracts/prediction_market.py`
- Source SHA256: `fc10458b147bd0e031c4a9ec087064baf47cdd22581a7f7d7fbe32b3b7f9e7f6`
- Source commit: `acfaf5e` (the deployed file is byte-identical to the file in this repository — see the SHA256 above)
- Runner: `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` (pinned; the network rejects the `latest`/`test` aliases)
- Live actors (ephemeral script accounts, addresses only): creator `0x0A1f89d650F290360c9FD41D9008f2Ef4DBaCfbF`, bettor_b `0x9c2F1917D11E3C8A0F13784Cf2Aa5c5E9E18d6D4`, bettor_c `0xf7a04fB68da837F2580A42C666eF571a84630bcd`

## Transactions

Every transaction below reached FINALIZED with leader execution `SUCCESS`. Full receipts and read-back state: [`live-verification.json`](live-verification.json).

| Step | Transaction hash | Status | Execution |
| --- | --- | --- | --- |
| deploy | `0xb05c47fb634ea15f12882619b174b1a510916b0e8f557dd883473020a017d282` | FINALIZED | SUCCESS |
| creator claim_test_gen | `0xf3faeb85ba0ca0cbf17d8eef5191443cacfea1a827c596c19828a686e9f23bb8` | FINALIZED | SUCCESS |
| bettor_b claim_test_gen | `0xb43135b3e0120fed229c23d861c6e6eeb90c96292996835a71c10097ad83cf67` | FINALIZED | SUCCESS |
| bettor_c claim_test_gen | `0xea64f0c08f7d868876f24d966bc99edc9247643c673e6594f47ce82ca535987d` | FINALIZED | SUCCESS |
| market1: create_market | `0x0d8833ef608a28b162a6d4ebbd0069533cb97cc7a0c52976f944d08b24d88eb5` | FINALIZED | SUCCESS |
| market1: bet creator 60 GEN on outcome 0 | `0x33a2784fe6a44447f1105cccf39c551c4f04b7a3c3a34b2ed26baa2ff11589c1` | FINALIZED | SUCCESS |
| market1: bet bettor_b 30 GEN on outcome 1 | `0x24993c5b00d81999a5126173844f3090dd2315ad8f46de43da4a2b3da67dd81f` | FINALIZED | SUCCESS |
| market1: bet bettor_c 10 GEN on outcome 2 | `0x33ea67595d0b224d01ceb2f4830dc1f3b37917cdc3ca4529876c832586bb9074` | FINALIZED | SUCCESS |
| market1: propose_outcome 0 | `0x487b7da6cc6855475e22688db86b8a76842be20199717f8d7a9bdac4e57f2273` | FINALIZED | SUCCESS |
| market1: adjudicate | `0xc754e8e4385b58b8d5f92f4eb5c5f452945917f7a4fea3fbac069cd17311e8bd` | FINALIZED | SUCCESS |
| market1: settle | `0x0279f6fa91eaa61ddd692800c23180c55ab79285825a2a0acb652412ef7663fe` | FINALIZED | SUCCESS |
| market2: create_market | `0xdcf1c2507d2177ed388097e9c0217a700d57fe333345730bc34cfc21eeaabc7c` | FINALIZED | SUCCESS |
| market2: bet creator 20 GEN on outcome 0 | `0x76f806266ae79ad0a94a93840dc6bc0713acb501e49257e4e7a95f2d2e2ebc1d` | FINALIZED | SUCCESS |
| market2: bet bettor_b 20 GEN on outcome 1 | `0xe4a8760b5089dccfac5bfca9cba4bfaba2fb07b42f94865a107dbea7a6eb735d` | FINALIZED | SUCCESS |
| market2: bet bettor_c 20 GEN on outcome 2 | `0xc546f6fd83e47c7c2ab4796f2249996e21d9e67760ca36258f56bd2c9f2d4103` | FINALIZED | SUCCESS |
| market2: propose_outcome 1 (evidence establishes 0) | `0x54f5fba5d8770b1c00c0d249769dbded787db8210cc2bdc1f6ccfeb94ea7470f` | FINALIZED | SUCCESS |
| market2: adjudicate | `0xa072ef79b35a041a247c1ea3ad55e8ffcf1aeede5915153e3543f1459bfe39b0` | FINALIZED | SUCCESS |
| market2: dispute claims 2 | `0x2447006ded25e74fb7c114ffbe091b1801056192e4a4e6f97377d9c2c10696db` | FINALIZED | SUCCESS |
| market2: adjudicate_dispute | `0x7dc17391aaacea491f594b5b611c984d335b00ea468812a791430fe71631edfc` | FINALIZED | SUCCESS |
| market2: settle | `0xd7ccac10d03147279c864bb3ba63f225dff5dc6ba7f46e565522630ac5f06351` | FINALIZED | SUCCESS |
| market3: create_market | `0x40850a1376e4fb9e3986617a0ab784a270f259351f031878567527e98af5a407` | FINALIZED | SUCCESS |
| market3: bet creator 10 GEN on outcome 0 | `0x33364a3ec91beeafb2ec68470f83c63822a67de209288ac4c05b18a5a1f33151` | FINALIZED | SUCCESS |
| market3: bet bettor_b 10 GEN on outcome 1 | `0x853d6f3b70dc8274dbd93df858c37d49175464ef2f06b6686753307b750db60d` | FINALIZED | SUCCESS |
| market3: bet bettor_c 10 GEN on outcome 2 | `0xe3f00a9a257d663f2a38cc393a44577242f1606aa6065149818e39fbd70e0a62` | FINALIZED | SUCCESS |
| market3: propose_outcome 0 (contradictory evidence) | `0xa038ca1c086e797e706c9cf5026e1d1d8cd1680463d517a36abe4bb02f35db9b` | FINALIZED | SUCCESS |
| market3: adjudicate | `0x4fc246b05272f963aa8bf6b29d9c84191e1f86d42eaf2b0b4370418216fdf2d4` | FINALIZED | SUCCESS |
| market3: settle | `0x1df6026cf0e4067ac3602eaeefeea72f6992a17b4886da98925546aa3898841c` | FINALIZED | SUCCESS |

## Final read-back (after all transactions)

- Market 1: `SETTLED_PAID`, verdict `OUTCOME|0`, pool was 100000000 microGEN in outcome totals 60000000|30000000|10000000.
- Market 2: `SETTLED_PAID`, verdict `OUTCOME|0`, pool was 60000000 microGEN in outcome totals 20000000|20000000|20000000.
- Market 3: `SETTLED_REFUNDED`, verdict `INVALID`, pool was 30000000 microGEN in outcome totals 10000000|10000000|10000000.
- Platform pool: 3 GEN (3200000 microGEN).
- Creator balance: 1076 GEN. Bettor B balance: 950 GEN. Bettor C balance: 970 GEN.

## Superseded deployments

None. The first deployment is the deliverable contract.
