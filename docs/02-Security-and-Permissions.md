# 02 - Security, Roles and Permissions

Source: IT-DOC-BP-001 sections 5, 7, 8.4 and Phases 2, 4, 5 and 6.

## 1. Authorization model

```text
File server : User → AD Global group (GG_) → AD Domain Local group (DL_) → NTFS ACE
SharePoint  : User → AD Global group → (Entra Connect sync) → SharePoint group → Permission level
```

- No employee gets a direct NTFS or SharePoint permission (REQ-16). The script only grants to groups.
- SharePoint access never implies file-server access, and the reverse is also true.
- External users get **no** SMB, VPN or file-server access and are never members of a site-wide group (REQ-08).
- Service identities are gMSAs (on-prem) and certificate-based Entra apps with `Sites.Selected` (cloud). No passwords or client secrets are stored in scripts.

## 2. Business roles

| Role | Who | Main capabilities |
| --- | --- | --- |
| Employee / Author | Licensed users | Collaborate in `Working`, register a document, create a revision, submit, create exchange requests |
| Document Owner | Named on the register item | Everything an author can do for their documents, plus cancel or restart their workflow |
| Approver | Anyone in the Approver Matrix, Impact Routing or a delegation | Approve or reject in Teams. Read `Submitted` |
| Final Approver | CEO, CTO, CIO, Quality Manager... per matrix | Stage-2 decision |
| Document Controller | Document Control team | Maintain matrix, routing and labels. Accept or reject exchange packages. Make obsolete. Fix failed file actions. Controlled modify on `Approved` |
| Auditor | Quality, InfoSec, internal audit | Read everything, including audit lists and version history |
| M365 / SharePoint Admin | IT | Full Control on both sites. No business decisions |
| Flow service account | One licensed, MFA-protected account that owns the flow connections | Add and edit list items. Never delete. Append-only on audit lists |
| Workflow Service (gMSA + Entra app) | On-prem integration server | Execute File Action Queue commands. Modify on controlled folders |
| Transfer Worker (gMSA + Entra app) | On-prem integration server | Graph download from Temporary Uploads, write to `05_Exchange_Quarantine\Inbound` only |
| External customer (B2B guest) | Invited per request | Upload to one request folder only |

## 3. Active Directory groups (file server)

Create these in a dedicated OU (for example `OU=DMS,OU=Groups`). Global groups hold people. Domain Local groups hold the Global groups and are the only principals on NTFS ACLs.

### 3.1 Global role groups (people)

| Group | Members | Synced to Entra |
| --- | --- | --- |
| `GG_DMS_Employees` | All licensed employees | Yes |
| `GG_DMS_Engineers` | Engineering, Development, Test, Manufacturing engineering | Yes |
| `GG_DMS_Management` | Management, CFT leads | Yes |
| `GG_DMS_Approvers` | Everyone who can appear in the approver matrix | Yes |
| `GG_DMS_DocumentControl` | Document Control team | Yes |
| `GG_DMS_Auditors` | Quality, InfoSec, internal audit | Yes |
| `GG_DMS_ITAdmins` | File-server and M365 admins (use separate admin accounts) | Yes |
| `GG_CFT_<CustomerCode>` | Customer Front Team per customer (isolation between customers) | Yes |
| `GG_DMS_PilotUsers` | 10-20 pilot employees (Phase 8) | Yes |

### 3.2 Domain Local resource groups (NTFS)

Pattern `DL_FS_<Scope>_<R|M>` where R = Read and M = Modify.

| Group | Folder | NTFS right | Contains |
| --- | --- | --- | --- |
| `DL_FS_<Area>_Working_M` | `...\Working` | Modify | `GG_DMS_Engineers` or the area's authors, `GG_DMS_DocumentControl` |
| `DL_FS_<Area>_Submitted_R` | `...\Submitted` | Read | `GG_DMS_Approvers`, area authors |
| `DL_FS_<Area>_Current_R` | `...\Current_ReadOnly`, `...\Obsolete_ReadOnly` | Read | `GG_DMS_Employees` (or a narrower group for confidential areas) |
| `DL_FS_<Area>_Controlled_M` | `Submitted`, `Current_ReadOnly`, `Obsolete_ReadOnly` | Modify (no Delete, no Change Permissions) | `GG_DMS_DocumentControl` |
| `DL_FS_Customer_<Code>_M` | `02_Customers\<Customer>` | Modify | `GG_CFT_<Code>`, `GG_DMS_DocumentControl` |
| `DL_FS_Quarantine_M` | `05_Exchange_Quarantine` | Modify | `GG_DMS_DocumentControl` |
| `DL_FS_Quarantine_Inbound_M` | `05_Exchange_Quarantine\Inbound` | Modify | `gMSA_DMS_Transfer$` only |
| `DL_FS_Workflow_M` | Every `Working`, `Submitted`, `Current_ReadOnly`, `Obsolete_ReadOnly`, `03_Operations_Staging`, `04_Workflow_System` | Modify | `gMSA_DMS_Workflow$` only |
| `DL_FS_Admin_F` | Root | Full Control | `GG_DMS_ITAdmins` |

Disable inheritance at the controlled folders and apply these ACEs (Phase 2 step 4). Keep `CREATOR OWNER` off controlled folders so that authors do not keep implicit rights after a move.

### 3.3 Repository permission matrix (blueprint 5.2, expanded)

| Role | Working | Submitted | Current (Approved) | Obsolete | Quarantine Inbound | Quarantine (other) |
| --- | --- | --- | --- | --- | --- | --- |
| Employee | Modify (own area) | None | Read | Read | None | None |
| Engineer / Author | Modify | Read | Read | Read | None | None |
| Approver | Read | Read | Read | Read | None | None |
| Document Controller | Modify | Modify | Controlled Modify | Controlled Modify | Modify | Modify |
| Auditor | Read | Read | Read | Read | Read | Read |
| Workflow Service | Modify | Modify | Modify | Modify | None | None |
| Transfer Worker | None | None | None | None | Modify | None |
| External customer | None | None | None | None | None | None |

## 4. SharePoint permission levels (created by the script)

Built-in levels are resolved by `RoleTypeKind`, so the script works on Hebrew sites where "Read" is displayed as "קריאה".

| Level (EN / HE) | Based on | Change | Used for |
| --- | --- | --- | --- |
| Full Control | built-in | - | Owners groups |
| Read | built-in | - | Members, approvers, auditors |
| Contribute | built-in | - | Exchange service account on Temporary Uploads only (it must delete expired content) |
| **DMS Document Controller** / DMS - בקר מסמכים | Contribute | + Approve items, Cancel checkout, Manage alerts. − Delete versions | Document Control groups |
| **DMS Service Contribute** / DMS - תרומה לשירות | Contribute | − Delete items, − Delete versions | Flow service account |
| **DMS Append Only** / DMS - הוספה בלבד | Read | + Add items | Flow service account on audit lists (items cannot be edited or deleted) |
| **DMS Upload Only** / DMS - העלאה בלבד | Contribute | − Delete items, − Delete versions, − Personal views, − Alerts | Per-request folders (employee and guest), granted by EX-01 |

## 5. SharePoint groups and list permissions

Add **Entra security groups** to these SharePoint groups, not individual people. Use the script's `-GroupMembers` parameter or do it afterwards.

### 5.1 Document Control site

| SharePoint group (EN / HE) | Entra group | Site level |
| --- | --- | --- |
| DMS Owners / DMS - בעלים | `GG_DMS_ITAdmins` | Full Control |
| DMS Document Controllers / DMS - בקרי מסמכים | `GG_DMS_DocumentControl` | DMS Document Controller |
| DMS Approvers / DMS - מאשרים | `GG_DMS_Approvers` | Read |
| DMS Members / DMS - עובדים | `GG_DMS_Employees` | Read |
| DMS Auditors / DMS - מבקרים | `GG_DMS_Auditors` | Read |
| DMS Service Accounts / DMS - חשבונות שירות | flow service account | DMS Service Contribute |

| List | Owners | Doc Controllers | Approvers | Members | Auditors | Service |
| --- | --- | --- | --- | --- | --- | --- |
| Document Register | FC | DMS Doc Controller | Read | Read | Read | Service Contribute |
| Approver Matrix, Impact Routing, Delegations, UI Labels | FC | DMS Doc Controller | Read | Read | Read | Service Contribute |
| Workflow History, Approval Decisions (unique) | FC | **Read** | Read | Read | Read | Service Contribute |
| File Action Queue (unique) | FC | Read | - | - | Read | Service Contribute |
| Control Audit (unique) | FC | Read | - | - | Read | **Append Only** |

Workflow history is read-only for Document Control on purpose. Decision history can only be written by the flow, which is what makes AC-12 ("Dynamic approver history is complete") provable.

The Workflow Service Entra app writes back to `File Action Queue` through Graph with `Sites.Selected` = Write on this site only. It is not a SharePoint group member.

### 5.2 Large File Exchange site

| SharePoint group | Entra group | Site level |
| --- | --- | --- |
| Exchange Owners | `GG_DMS_ITAdmins` | Full Control |
| Exchange Document Control | `GG_DMS_DocumentControl` | DMS Document Controller |
| Exchange Employees | `GG_DMS_Employees` (**never guests**) | Read |
| Exchange Auditors | `GG_DMS_Auditors` | Read |
| Exchange Service Accounts | flow service account | DMS Service Contribute |

| List | Owners | Doc Control | Employees | Auditors | Service |
| --- | --- | --- | --- | --- | --- |
| Temporary Uploads (unique) | FC | DMS Doc Controller | - (per-folder grant only) | - | Contribute |
| Upload Requests (unique) | FC | DMS Doc Controller | Read | Read | Service Contribute |
| Routing Catalog (unique) | FC | DMS Doc Controller | Read | Read | Read |
| Exchange Audit (unique) | FC | Read | - | Read | Append Only |

Per-request folder (created by EX-01): inheritance broken, `DMS Upload Only` for the requester and the invited guest, `DMS Document Controller` for Exchange Document Control. Access is removed by EX-07 / EX-05 after transfer or expiry.

## 6. Lifecycle permission matrix

What each role can do at each document state. SharePoint rows show who may *trigger* the change, and the flow service account performs the write.

| State | Author / Owner | Approver | Document Controller | Workflow Service |
| --- | --- | --- | --- | --- |
| Working | Edit file (SMB). Register, submit | Read file | Edit, re-assign owner | - |
| Submitted | Read. Cancel or restart own workflow | Read. Approve or reject in Teams | Read. Cancel any workflow | Moves file, sets read-only |
| Approved_ReadOnly | Read. Create new revision | Read | Controlled modify of metadata. Make obsolete. Release to PLM | Promotes file, obsoletes previous revision |
| Released_PLM | Read | Read | Read. Correct references | Copies to PLM queue with manifest |
| Obsolete_ReadOnly | Read | Read | Archive | Moves to Archive |
| Archived | - | - | Read | - |

## 7. Tenant and site hardening

The script does the following.

| Setting | Document Control site | Exchange site |
| --- | --- | --- |
| `SharingCapability` | `Disabled` | `ExternalUserSharingOnly` (authenticated guests, **no anonymous links**) |
| Default link type | - | `Direct` (Specific people) |
| Allowed guest domains | - | `-AllowedGuestDomains` → allow-list mode |
| Members can share | No | No |
| Sharing by non-owners | Disabled | Disabled |
| List attachments | Off everywhere | Off everywhere |
| Temporary Uploads versioning | - | Off (the script warns if the tenant enforces versioning. Then set the smallest allowed limit) |

Do these manually in the admin centers because they are tenant-wide.

1. SharePoint admin center → Policies → Sharing → turn off *Allow guests to share items they don't own*. Set guest access to expire (for example 30 days).
2. Entra ID → External collaboration → restrict invitations to admins and the *Guest Inviter* role held by Document Control. Use a domain allow-list where practical.
3. Entra ID → Conditional Access → require MFA for all users, including guests, and for admin roles.
4. Power Platform admin center → DLP policy for the DMS environment. The **Business** group has SharePoint, Microsoft Teams, Office 365 Users, Approvals and Office 365 Groups. Every other connector is **Blocked**, including File System, HTTP and the on-premises data gateway.
5. Entra app `RH-Exchange-Transfer-Worker` → Microsoft Graph `Sites.Selected` (application) + admin consent. The script's `-TransferWorkerAppId` grants **Write** on the Exchange site only. Never grant `Sites.ReadWrite.All`.
6. Entra app `RH-DMS-Workflow-Service` → the same pattern with `-WorkflowServiceAppId` on the Document Control site.
7. Certificates for both apps are in `LocalMachine\My` on the integration server, the private key is readable only by the gMSA, and there is a renewal alert 60 days before expiry.
8. Purview (where licensed) → retention label *DMS Record 7Y* applied to Control Audit, Exchange Audit, Workflow History and Approval Decisions. The Temporary Uploads library is **excluded** from retention policies, or the deleted cloud copies would be kept in the Preservation Hold library.

## 8. Dynamic approver policy (blueprint 7)

1. Approvers are chosen for **each submitted revision**.
2. **Mandatory + Final** approvers from the Approver Matrix are locked in the app and re-checked in DC-03 on the server side.
3. **Change Impact** selections add the Impact Routing approvers, which are also locked.
4. **Conditional** approvers from the matrix are pre-selected suggestions. Removing one requires a justification that is written to the audit list.
5. The requester may **add** reviewers but cannot remove locked approvers.
6. Changing approvers after submission cancels the cycle and starts a new one (`CycleNumber + 1`).
7. Delegation must be formal, time-limited (`ValidFrom` / `ValidTo`), approved (`DelegationApprovedBy`) and recorded. DC-04 swaps the approver for the active delegate and writes `DelegatedFrom`.
8. A rejection by any stage-1 approver or by the final approver returns the revision to `Working`.
9. Submitters cannot approve their own revision. DC-03 removes the submitter from the approver set and, when the submitter was a locked approver, routes that slot to the Document Control group.
