# DMS deck generator

`DMS-Approval-Flow.pptx` (pilot process and user training, Hebrew) is built from these scripts.

```powershell
cd docs\presentations\build; npm install pptxgenjs; node deck.js
```

`deck.js` holds slides 1-5 (pilot process), `training.js` the user training slides. Edit the text there and rebuild rather than editing the .pptx by hand.
