# VAL-006 Validation Summary Report

| | |
|---|---|
| Software revision | 01 - the whole validation set carries one version (`validation.json`) |
| System | RH DMS, `https://dms.rh.tech` |
| Build validated (`/api/health` → `version`) | |
| Period | IQ ______ · OQ ______ · PQ ______ to ______ |
| Prepared by | |

## 1. What was validated

The DMS as described in VAL-001, against the specifications in `docs/01` to `docs/09`, by the three
qualifications VAL-002 (IQ), VAL-003 (OQ) and VAL-004 (PQ).

## 2. Result

| Qualification | Steps | Passed | Deviations (critical / major / minor) | Report |
|---|---|---|---|---|
| IQ | 16 | | | VAL-002 |
| OQ | 25 | | | VAL-003 |
| PQ | 15 + feedback | | | VAL-004 |

Supporting evidence attached: the automated test run (`webapi\tests`), the end-to-end walk report
(`%TEMP%\DMS-Smoke <date>.txt`), the IQ/OQ/PQ machine-written reports, and the Control Audit export for the
PQ period.

## 3. Deviations and their disposition

| # | From | Class | Summary | Disposition | Closed |
|---|---|---|---|---|---|
| | | | | | |

No critical deviation remains open. (If one does, this report says so and the system is not accepted.)

## 4. Residual risk and controls

| Risk | Control |
|---|---|
| A group change in AD reaches a machine caller late (the account's rights are read once and kept until the application pool recycles) | Known and documented; an urgent change is applied by restarting the DMS (`Restart-Dms.ps1`) |
| The Approver Matrix routes a document to the wrong people if a rule is wrong | The matrix is maintained by Document Control and reviewed at each internal audit; the approvers are shown on the page before submission |
| A document released without workflow is approved by whoever copied it | Allowed only to people with Write in that folder, written to the audit as "released without workflow", and reported monthly |
| The AI quotes an obsolete revision | The AI reads `Current_ReadOnly` only; a superseded file is moved out of it on release |

## 5. Conclusion

The RH DMS **is / is not** validated for production use for controlled documents, with the controls above.

## 6. Approval

| Role | Name | Signature | Date |
|---|---|---|---|
| System owner | | | |
| Document Control | | | |
| Quality | | | |
