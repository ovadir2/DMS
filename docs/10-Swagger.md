# 10 - Swagger: the API other systems use

Four calls, and nothing else: ask for a ticket, read what is released, fetch what you need, and look up where things live. Written from the API itself (`python -m dms_api.apidocs`, or `scripts\New-DmsApiDocs.ps1`), so it cannot drift.

| | |
| --- | --- |
| **Try it** | `https://dms.rh.tech/dms/api-try` - the four calls from a page, as you, with your own AD rights. Nothing to install |
| **Swagger UI** | `https://dms.rh.tech/dms/api-docs` (ReDoc: `/dms/api-redoc`) |
| **The address** | the document carries this DMS's own base URL (`servers`), so a generated client needs none written by hand |
| **The document** | `https://dms.rh.tech/api/openapi.json`, and `dms-swagger.json` beside this file, to generate a client without reaching the server |
| **The rest of it** | WidgetBuilder's publish call: `08-WidgetBuilder-Contract.md`. The search, the page key and the AI's guide: `09-Machine-API.md`. The DMS page's own ~80 endpoints: `/api/openapi-all.json` |

Written from DMS 7a6f3f1.

## How a caller is known

| | How it signs in | What it may do |
| --- | --- | --- |
| An application | `X-DMS-Api-Key: <key>` or `Authorization: Bearer <key>` | the key's scopes, as the AD account the key acts as |
| The company's AI | `?ticket=` or `X-DMS-Index-Ticket` (from `/api/ai/index-ticket`) | what the person who asked may read, file by file |
| A person | Windows authentication, to ask for a ticket | their own rights |

## AI Insights

Questions about a document or about the company's knowledge, asked of the RH AI portal. The DMS never sends a file the person may not read.

### GET /api/ai/index-ticket

A ticket the company's AI uses to index what this person may read, just before it answers them.

The RAG is given it by the page when the person asks AI Insights, and calls
/api/v1/approved-documents with it. Everything it gets back is filtered by that person's own AD
rights, file by file - an application key names a service account and would answer the same list to
everybody, which is exactly what must not happen here.

It answers:

```json
{
 "ticket": "Qm9iLXRpY2tldC0yMDI2",
 "hours": 8,
 "documents": "https://dms.rh.tech/api/v1/approved-documents?ticket=Qm9iLXRpY2tldC0yMDI2",
 "search": "https://dms.rh.tech/api/v1/search?ticket=Qm9iLXRpY2tldC0yMDI2&q=",
 "header": "X-DMS-Index-Ticket"
}
```

## The machine API

An application, not a person: a key (X-DMS-Api-Key, or Authorization: Bearer) that names what it may read and the AD account it acts as. The DMS answers it exactly what that account may see.

### GET /api/v1/approved-documents

The Markdown of every approved document, as it lies in the Current_ReadOnly folders.

Four things per file: the document's id, its name, its revision and where the Markdown is. This is
the AI's list - it reads these files - so it is taken from the folders themselves and not only from
the register: a document released by hand is in Current_ReadOnly with its Markdown beside it, and the
AI should read that too. What the register knows fills in the id and the revision; what it does not
know is read from the Markdown's own first lines, which the DMS wrote when it made the file.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `customer` | query | no | string |  |
| `q` | query | no | string |  |
| `ticket` | query | no | string | An indexing ticket (/api/ai/index-ticket): the answer is then what that person may see, not what a service account may |
| `since` | query | no | string | Only files changed after this moment (2026-11-15T08:00:00Z): what an index needs on a second run |
| `inline` | query | no | boolean | Carry the Markdown itself in the answer, so an index needs no second call per document (a few KB each, and a budget it stops at) |
| `budget` | query | no | integer | How many characters of Markdown this answer may carry with inline=true |
| `all` | query | no | boolean | Also the released files that have no Markdown of their own (a drawing, a picture) |
| `readable` | query | no | boolean | Only documents with text in them - an index built on an LLM has nothing to do with a drawing's card |
| `format` | query | no | string | ndjson streams one document per line, so a repository of thousands is read as it is built, at a flat memory cost on both sides |
| `manifest` | query | no | boolean | Only the shape of the answer - how many documents, how many bytes, and the tag of the whole set - so an index knows in one cheap call whether anything changed |

It answers:

```json
{
 "documents": [
  {
   "DocID": "QP-16.1",
   "DocName": "Control of documents",
   "DocRev": "03",
   "DocFile": "E:\\Shares\\01_General\\Quality\\Current_ReadOnly\\QP-16.1 Rev03.docx",
   "DocFileName": "QP-16.1 Rev03.docx",
   "DocDMSpath": "E:\\Shares\\01_General\\Quality\\Current_ReadOnly\\QP-16.1 Rev03.md",
   "url": "https://dms.rh.tech/api/v1/file?path=E%3A%5CShares%5C...%5CQP-16.1%20Rev03.docx&ticket=Qm9i",
   "markdownUrl": "https://dms.rh.tech/api/v1/file?path=E%3A%5CShares%5C...%5CQP-16.1%20Rev03.md&ticket=Qm9i",
   "markdown": "# Control of documents\n\n- Document ID: QP-16.1\n- Revision: 03\n\n---\n\n## 1. Purpose ...",
   "etag": "\"9f2c41a7be03d5f1\"",
   "modifiedUtc": "2026-11-15T07:12:04Z",
   "size": 7431,
   "folder": "E:\\Shares\\01_General\\Quality\\Current_ReadOnly",
   "customer": "",
   "hasMarkdown": true,
   "files": [
    {
     "name": "QP-16.1 Rev03.docx",
     "path": "E:\\Shares\\...",
     "size": 182144
    },
    {
     "name": "QP-16.1 Rev03.md",
     "path": "E:\\Shares\\...",
     "size": 7431
    }
   ]
  }
 ],
 "count": 1
}
```

### GET /api/v1/file

One released file, served by the DMS itself - the content, not a path on the file server.

This is how the company's AI reads a document without an account on the file server: it asks for the
file, and the DMS answers only if the AD account behind the call may see it - the key's own account,
or, with a ticket, the person who asked. Only what is released (Current_ReadOnly) is served, so an
index built from this holds the revisions in force and nothing in work.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `path` | query | yes | string |  |
| `markdown` | query | no | boolean | The Markdown written beside the document, rather than the document itself |
| `ticket` | query | no | string | An indexing ticket (/api/ai/index-ticket) |

### GET /api/v1/structure

Where documents live: the departments of the company and the customers, in one answer.

Each carries its folder and its KPIs folder (and whether that folder has been made yet), so an
application knows where it may publish and an index knows what it is walking. AD decides here as
everywhere: what the account behind the call may not see is not in the answer.

| Parameter | In | Required | Type | |
| --- | --- | --- | --- | --- |
| `q` | query | no | string |  |
| `ticket` | query | no | string | An indexing ticket (/api/ai/index-ticket): the answer is then what that person may see |

It answers:

```json
{
 "departments": [
  {
   "name": "Quality",
   "label": "Quality",
   "path": "E:\\Shares\\01_General\\Quality",
   "kpis": "E:\\Shares\\01_General\\Quality\\KPIs",
   "kpisExists": true
  }
 ],
 "customers": [
  {
   "name": "Elbit",
   "path": "E:\\Shares\\02_Customers\\Elbit",
   "kpis": "E:\\Shares\\02_Customers\\Elbit\\KPIs",
   "kpisExists": false
  }
 ],
 "counts": {
  "departments": 14,
  "customers": 23
 }
}
```
