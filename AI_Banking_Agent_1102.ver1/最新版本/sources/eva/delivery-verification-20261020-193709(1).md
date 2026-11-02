# Delivery Verification · Risk & Compliance

- 时间：2026-10-20T19:37:09+08:00
- 结果：passed
- 测试：42 tests
- Demo：completed · 3 logs

## Manifest

| 文件 | SHA-256 |
|---|---|
| `bank_agent/__init__.py` | `4bb0098cff1c8453b9da2170a39b2c973844a935930df83fc59c567af281436e` |
| `bank_agent/models.py` | `b1a16894e9c9fed4dda2c0fdaf67407e4348590cf8a04afd54d51ddf5425da7d` |
| `bank_agent/data.py` | `4d6844e1ee3f630651a6110a8fbde815332d136a83bbcb1642b5eb9630bd9a48` |
| `bank_agent/policy_config.json` | `f0c0416092740facfeb908f5a8381dbbd1fc10bc603a05f7935a69a906aa8924` |
| `bank_agent/tools.py` | `744d9f5941a8c9a5c04cf6903d0af2bcb54126a0b4c189c80370ac499d4147c0` |
| `bank_agent/orchestrator.py` | `cd0339a684dc98decbadcbea6fd75f311ab77b10ed6e05344df9ec10101f0134` |
| `bank_agent/brain.py` | `b5d1945b074c58afd9cee940f362603b6694475feb80a0a1e1701cae4a59685e` |
| `bank_agent/stages/execution.py` | `2e66c041830f08e2aa77c818e735f497703d6685530ec2254bf9a10881ccb2f7` |
| `bank_agent/stages/selection.py` | `54504a44fa0785305b4d1f31bef39260164221758190d97d8aac33a57e824982` |
| `bank_agent/risk/__init__.py` | `10332ee33e0d40c846d8de8b125c78a4c5ef62b6f1ff0d2b37b99988a6c904f2` |
| `bank_agent/risk/models.py` | `9602a49754b099c3160f1f3f3efbf4956de816dc78978effa6dd18d58fb4d638` |
| `bank_agent/risk/policy.py` | `fdb27988f2b929e05b913c57a780d6ea3b1b23a4a5ae24db2dd345630d9c269c` |
| `bank_agent/risk/preview.py` | `8f4aa7bd343473fead293b3e8d929f7f056f8d0bb1899a605052e53f1ad34707` |
| `bank_agent/risk/auth.py` | `576fd7ca9e4612b849a5f0691645e44ebcac2733e5ff7ac67357227aecaf3c2e` |
| `bank_agent/risk/compliance.py` | `6f67460dcda2dbd48e06b64cbabbd895a75777e444e82668157d411f101c8b11` |
| `bank_agent/risk/controls.py` | `7a455d882c5ba3bfa9247c25a8fd46160ae131c2ec799242da0af3af12d06f57` |
| `bank_agent/risk/action_log.py` | `f253ac146102a1547b02b45d24c484a37c592af247081f118b104cfb54fe2ea0` |
| `bank_agent/risk/engine.py` | `ba3b626d039421fa91726c2acf8cafc39cb287cee10de6ea731da2f7835261dd` |
| `tests/test_pipeline.py` | `e7b431f196ac4a152a92dcd9f54b4f37a95bee319b121ee9e54545c06bed0554` |
| `tests/test_risk_compliance.py` | `d51470b37979ccda1f8942dc6d9a55bec3b4687280777d50161ea6e87d449563` |
| `docs/05-action-log-spec.md` | `e0a2b05123e7dc23f1b3daebd8c56d881c945c0f4b38e9e4457bbff2efc02012` |
| `docs/06-risk-compliance.md` | `8fcb8db38600f03f54a9fb1c485e77c8f4ecf582b14dad8d8534c79699830799` |
| `docs/07-compliance-control-matrix.md` | `b85a85b64f391e2597c4d18eac5b75c2d1451d513625bdc6eeec43d4d47cc1bf` |
| `run_demo.py` | `1a7c82689556f73798cd8cb011d74c15c869e08e049ee2b1e0cd5d6dbb557c8e` |
| `README.md` | `9394cdd76d7ebecb7c720f51456dd3e03f0fc5073064fb97965aedf445aeb874` |
| `scripts/verify_delivery.py` | `2fb780452da253b658cbd710a2bfc7ab5ef0c524a2fbc1b8c93e2af4a30a01cf` |
| `bank_agent/stages/planning.py` | `f6856984edfbec49215aabf3c27c46f5f0ad48790ac16cec029dd4c519c7129f` |
| `bank_agent/stages/verification.py` | `6253aba2cf9a4e1339de9c44e42c4b2a0885e9192e9e7e6a56f2099ae47261df` |
| `bank_agent/stages/response.py` | `9206a9281e7fe90ae52aa29e753dc6f27f81570ea13740938217791cb1e661c8` |
| `bank_agent/stages/intent.py` | `675f04f8c109ce73866a2bd614659f6f1ef6636bde682e4ea235ae366db62e77` |
| `bank_agent/utils.py` | `dea76e95ae4354c33979ebdd8afad72f523dd602909aa7df4bf592c78e689276` |

## 复现

```bash
python3 scripts/verify_delivery.py
```

## Agent Action

```json
{
  "user_id": "team:delivery-verification",
  "intent": "verify_risk_compliance_delivery",
  "tool": "delivery.verify@1.0.0",
  "input": "{\"required_files\":25,\"test_command\":\"python3 -m unittest discover -s tests -v\"}",
  "output": "{\"status\":\"passed\",\"tests\":\"42 tests\",\"demo\":\"completed · 3 logs\",\"demo_log_count\":3,\"demo_tools\":[\"orchestrator.confirmation@1.0.0\",\"transfer.preview@1.0.0\",\"transfer_funds@1.0.0\"],\"manifest_files\":31,\"static_checks\":\"no_eval_exec_dynamic_import\",\"problems\":[]}",
  "risk_check": "{\"mutating\":false,\"real_funds\":false,\"pii_scan\":\"passed\",\"external_side_effects\":false}",
  "approval": "{\"required\":false,\"reason\":\"verification_only\",\"decision\":\"not_required\"}",
  "timestamp": "2026-10-20T19:37:09+08:00"
}
```
