const pptxgen = require('pptxgenjs');
const pres = new pptxgen(); pres.layout = 'LAYOUT_WIDE'; pres.rtlMode = true;
pres.title = 'DMS pilot and user training';
const C = { ink:'1B2A33', muted:'5D6F7A', accent:'0E6F73', soft:'D9EEEE', laneA:'EEF3F5', laneB:'F8FAFB', ok:'2F7D32', no:'B3261E', noSoft:'FBE4E2', white:'FFFFFF', line:'C9D3D9' };
const F = 'Arial';
const he = (o) => Object.assign({ fontFace: F, rtlMode: true, lang: 'he-IL', isTextBox: true }, o);

// ---------- slide 1: title
let s = pres.addSlide(); s.background = { color: C.accent };
s.addText('DMS · פיילוט', he({ x: 0.8, y: 1.6, w: 11.7, h: 0.5, fontSize: 18, color: 'CFE9E9', bold: true, align: 'right', margin: 0 }));
s.addText('תהליך הפיילוט והדרכת משתמשים', he({ x: 0.8, y: 2.2, w: 11.7, h: 1.2, fontSize: 48, color: C.white, bold: true, align: 'right', margin: 0 }));
s.addText('RH - מערכת ניהול מסמכים: מהקובץ בשרת, דרך דף ה-DMS והאישור, ועד נעילה לקריאה בלבד ושיתוף עם לקוחות', he({ x: 0.8, y: 3.5, w: 11.7, h: 0.95, fontSize: 20, color: 'E6F4F4', align: 'right', margin: 0 }));
s.addText('DMS page · SharePoint · Power Automate · Large File Exchange · OneDrive · AI Insights', { x: 0.8, y: 6.3, w: 11.7, h: 0.4, fontSize: 14, color: 'CFE9E9', fontFace: F, align: 'right', isTextBox: true, margin: 0 });

// ---------- slide 2: end-to-end pilot flow (serpentine, right-to-left then left-to-right)
s = pres.addSlide(); s.background = { color: C.white };
s.addText('תהליך הפיילוט מקצה לקצה', he({ x: 0.4, y: 0.3, w: 12.5, h: 0.65, fontSize: 30, bold: true, color: C.ink, align: 'right', margin: 0 }));
s.addText('מהקובץ בשרת הקבצים, דרך דף ה-DMS ומסך האישורים, ועד הגרסה המאושרת לקריאה בלבד', he({ x: 0.4, y: 0.92, w: 12.5, h: 0.4, fontSize: 14, color: C.muted, align: 'right', margin: 0 }));
const ACT = { user: ['משתמש · דף DMS', '0E6F73'], fs: ['שרת הקבצים', '6B7684'], sp: ['SharePoint', '1F5FA8'], pa: ['מאשרים · דף DMS / Teams', '6D3FC0'], ws: ['שירות התהליכים', 'A86400'] };
const BW = 2.15, BH = 1.6, GAP = 0.33, X0 = 0.62, R1 = 1.7, R2 = 4.25;
const colX = i => X0 + i * (BW + GAP);
function card(i, row, num, actor, title, sub) {
  const x = colX(i), y = row === 1 ? R1 : R2, [label, col] = ACT[actor];
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: BW, h: BH, rectRadius: 0.08, fill: { color: C.white }, line: { color: col, width: 1.5 } });
  s.addShape(pres.shapes.RECTANGLE, { x: x + 0.02, y: y + 0.02, w: BW - 0.04, h: 0.34, fill: { color: col }, line: { color: col } });
  s.addText(label, he({ x: x + 0.05, y: y + 0.02, w: BW - 0.55, h: 0.34, fontSize: 10, bold: true, color: C.white, align: 'right', valign: 'middle', margin: 0 }));
  s.addShape(pres.shapes.OVAL, { x: x + 0.08, y: y + 0.04, w: 0.3, h: 0.3, fill: { color: C.white }, line: { color: C.white } });
  s.addText(String(num), { x: x + 0.08, y: y + 0.04, w: 0.3, h: 0.3, fontSize: 11, bold: true, color: col, fontFace: F, align: 'center', valign: 'middle', margin: 0, isTextBox: true });
  s.addText([{ text: title, options: { bold: true, fontSize: 12.5, color: C.ink, breakLine: true } }, { text: sub, options: { fontSize: 10, color: C.muted } }],
    he({ x: x + 0.1, y: y + 0.42, w: BW - 0.2, h: BH - 0.5, align: 'right', valign: 'top', margin: 0 }));
}
const arrow = (x1, y1, x2, y2, color, dash) => s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1),
  flipH: x2 < x1, flipV: y2 < y1, line: { color, width: 1.75, dashType: dash || 'solid', endArrowType: 'triangle' } });
// row 1: steps 1-5 from right to left
const row1 = [['user', 'בחירת מיקום', 'לקוח › תיקייה לפי עץ הבלופרינט, רק מה ש-AD מאפשר'], ['user', 'שמירת הקובץ', 'העלאה לתיקייה (או "מה שומרים?"). הקובץ בתיקייה, בעבודה'],
  ['user', 'שליחה לאישור', 'Start workflow: סוג מסמך, תחום, רישום והגשה'], ['sp', 'רשומה במרשם', 'מזהה DMS-xxxxx, סטטוס: הוגש לאישור, יומן: נוצר + הוגש'],
  ['ws', 'נעילה להגשה', 'הקובץ עובר ל-Submitted, קריאה בלבד, SHA-256']];
row1.forEach(([a, t, b], k) => card(4 - k, 1, k + 1, a, t, b));
for (let k = 0; k < 4; k++) arrow(colX(4 - k), R1 + BH / 2, colX(3 - k) + BW, R1 + BH / 2, C.ink);
arrow(colX(0) + BW / 2, R1 + BH, colX(0) + BW / 2, R2, C.ink);
// row 2: steps 6-10 from left to right
const row2 = [['pa', 'אישור שלב 1', 'כל מאשרי החובה לפי מטריצת המאשרים, במסך האישורים בדף'], ['pa', 'אישור סופי', 'המאשר הסופי, במסך האישורים בדף'],
  ['sp', 'מאושר', 'סטטוס: מאושר - קריאה בלבד, ההחלטה ביומן הביקורת'], ['ws', 'גרסה נוכחית', 'הקובץ ל-Current_ReadOnly, הקודם ל-Obsolete_ReadOnly, נתיב + SHA-256 למרשם'],
  ['user', 'מעקב וחיפוש', 'תהליכי האישור שלי, סטטוס על כל קובץ, חיפוש ו-AI Insights']];
row2.forEach(([a, t, b], k) => card(k, 2, k + 6, a, t, b));
for (let k = 0; k < 4; k++) arrow(colX(k) + BW, R2 + BH / 2, colX(k + 1), R2 + BH / 2, k < 2 ? C.ok : C.ink);
// rejection
const RY = R2 + BH + 0.32;
s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: colX(0), y: RY, w: 2 * BW + GAP, h: 0.62, rectRadius: 0.08, fill: { color: C.noSoft }, line: { color: C.no, width: 1.25, dashType: 'dash' } });
s.addText('נדחה בשלב 1 או 2: הסטטוס חוזר לבעבודה, הקובץ חוזר למקומו וניתן לעריכה, ההערה מופיעה בתהליכי האישור שלי. מתקנים ושולחים שוב (שלב 3).',
  he({ x: colX(0) + 0.1, y: RY, w: 2 * BW + GAP - 0.2, h: 0.62, fontSize: 10, color: C.no, align: 'right', valign: 'middle', margin: 0 }));
arrow(colX(0) + BW / 2, R2 + BH, colX(0) + BW / 2, RY, C.no, 'dash');
arrow(colX(1) + BW / 2, R2 + BH, colX(1) + BW / 2, RY, C.no, 'dash');
// legend
Object.values(ACT).forEach(([label, col], k) => {
  const x = 12.4 - k * 2.0;
  s.addShape(pres.shapes.RECTANGLE, { x: x + 0.62, y: 6.95, w: 0.22, h: 0.22, fill: { color: col }, line: { color: col } });
  s.addText(label, he({ x: x - 0.95, y: 6.9, w: 1.52, h: 0.32, fontSize: 10, color: C.muted, align: 'right', valign: 'middle', margin: 0 }));
});
s.addText('בפיילוט כל השלבים מתבצעים בדף ה-DMS, גם האישורים (תהליך DC-P1 כבוי). בייצור האישורים יגיעו ב-Teams.', he({ x: 7.0, y: 6.5, w: 5.9, h: 0.35, fontSize: 10.5, color: C.muted, align: 'right', margin: 0 }));
s.addNotes('1-3 המשתמש בדף ה-DMS. 4 SharePoint. 5 ו-9 שירות התהליכים מזיז את הקובץ ונועל. 6-7 אישור לפי מטריצת המאשרים, בפיילוט במסך האישורים בדף ובייצור ב-Teams. 8 סטטוס מאושר. 10 מעקב. דחייה מחזירה לשלב 3.');

// ---------- slide 3: where the file is
s = pres.addSlide(); s.background = { color: 'F5F7F8' };
s.addText('איפה הקובץ בכל שלב', he({ x: 0.6, y: 0.45, w: 12.1, h: 0.75, fontSize: 32, bold: true, color: C.ink, align: 'right', margin: 0 }));
const hdr = o => Object.assign({ bold: true, color: C.white, fill: { color: C.accent } }, o);
const rows = [
  [{ text: 'קריאה בלבד', options: hdr() }, { text: 'מיקום הקובץ (דוגמה: הצעות מחיר)', options: hdr() }, { text: 'סטטוס במרשם', options: hdr() }],
  ['לא', '...\\Commercial\\Quotations\\Quote.xlsx (היכן שנשמר)', 'בעבודה'],
  ['כן', '...\\Quotations\\Submitted\\Quote.xlsx', 'הוגש לאישור'],
  ['כן', '...\\Quotations\\Current_ReadOnly\\Quote.xlsx', 'מאושר - קריאה בלבד'],
  ['כן', '...\\Quotations\\Obsolete_ReadOnly\\...', 'גרסה מאושרת קודמת'],
  ['-', '$Root\\04_Workflow_System\\Recycle\\<תאריך>\\<משתמש>\\...', 'נמחק מהדף'],
].map(r => r.map(c => typeof c === 'string' ? { text: c, options: {} } : c));
s.addTable(rows, { x: 0.8, y: 1.5, w: 11.7, colW: [1.6, 6.6, 3.5], fontFace: F, fontSize: 14, color: C.ink, align: 'right', rtlMode: true, lang: 'he-IL',
  border: { type: 'solid', color: C.line, pt: 1 }, fill: { color: C.white }, rowH: 0.62, valign: 'middle' });
s.addText('שירות התהליכים מזיז את הקובץ לפי הסטטוס, נועל אותו לקריאה בלבד ורושם כל העברה ביומן הביקורת. הוא לעולם לא מעדכן רשומה בזמן שהיא הוגשה לאישור, כך שתהליך האישור לא מופעל פעמיים.',
  he({ x: 0.8, y: 5.6, w: 11.7, h: 0.9, fontSize: 14, color: C.muted, align: 'right', valign: 'top', margin: 0 }));

// ---------- slide 4: swimlane flow (approval detail)
s = pres.addSlide(); s.background = { color: C.white };
s.addText('תהליך האישור בייצור: Teams ו-DC-P1 (פירוט)', he({ x: 0.4, y: 0.35, w: 12.5, h: 0.7, fontSize: 32, bold: true, color: C.ink, align: 'right', margin: 0 }));
const sc = 0.0103, X = x => 0.4 + x * sc, Y = y => 1.3 + y * sc, W = w => w * sc;
const lanes = [['בעל המסמך','מגיש ומקבל תוצאה',0,110,C.laneA],['SharePoint','רשימות האתר',110,110,C.laneB],['Power Automate','DC-P1 Pilot Approval',220,110,C.laneA],['מאשרי חובה','Teams ומייל',330,110,C.laneB],['מאשר סופי','Teams ומייל',440,120,C.laneA]];
for (const [t, sub, y, h, col] of lanes) {
  s.addShape(pres.shapes.RECTANGLE, { x: X(0), y: Y(y), w: W(1200), h: W(h), fill: { color: col }, line: { color: col } });
  s.addText([{ text: t, options: { bold: true, fontSize: 13, color: C.ink, breakLine: true } }, { text: sub, options: { fontSize: 10, color: C.muted } }],
    he({ x: X(1075), y: Y(y), w: W(120), h: W(h), align: 'center', valign: 'middle', margin: 0 }));
}
s.addShape(pres.shapes.LINE, { x: X(1070), y: Y(0), w: 0, h: W(560), line: { color: C.line, width: 1 } });
function seg(pts, color, dash, arrow) {
  for (let i = 0; i < pts.length - 1; i++) {
    const [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
    const o = { x: X(Math.min(x1, x2)), y: Y(Math.min(y1, y2)), w: W(Math.abs(x2 - x1)), h: W(Math.abs(y2 - y1)),
      line: { color, width: 1.75, dashType: dash || 'solid' }, flipH: x2 < x1, flipV: y2 < y1 };
    if (arrow && i === pts.length - 2) o.line.endArrowType = 'triangle';
    s.addShape(pres.shapes.LINE, o);
  }
}
seg([[928,55],[912,55]], C.ink, null, true);
seg([[860,85],[860,275],[792,275]], C.ink, null, true);
seg([[688,275],[672,275]], C.ink, null, true);
seg([[620,305],[620,385],[552,385]], C.ink, null, true);
seg([[500,415],[500,495],[432,495]], C.ok, null, true);
seg([[328,495],[260,495],[260,305]], C.ok, null, true);
seg([[260,245],[260,165],[192,165]], C.ink, null, true);
seg([[500,355],[500,305]], C.no, 'dash', true);
seg([[380,465],[380,275],[448,275]], C.no, 'dash', true);
seg([[500,245],[500,122],[140,122],[140,135]], C.no, 'dash', true);
seg([[620,195],[620,245]], C.muted, 'sysDot', false);
seg([[980,85],[980,135]], C.muted, 'sysDot', false);
const tag = (t, x, y, col) => s.addText(t, he({ x: X(x - 40), y: Y(y - 12), w: W(80), h: W(18), fontSize: 10, bold: true, color: col, align: 'center', margin: 0 }));
tag('אושר', 468, 483, C.ok); tag('אושר', 292, 483, C.ok); tag('נדחה', 532, 332, C.no); tag('נדחה', 352, 396, C.no);
tag('קריאה', 656, 222, C.muted); tag('רשומה', 1016, 112, C.muted);
function box(x, y, t, sub, kind, num) {
  const fill = kind === 'start' ? C.accent : kind === 'store' ? C.soft : kind === 'no' ? C.noSoft : C.white;
  const stroke = kind === 'no' ? C.no : C.accent, tc = kind === 'start' ? C.white : C.ink, sc2 = kind === 'start' ? 'E6F4F4' : C.muted;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: X(x), y: Y(y), w: W(104), h: W(60), rectRadius: 0.08, fill: { color: fill }, line: { color: stroke, width: 1.5 } });
  s.addText([{ text: t, options: { bold: true, fontSize: 11, color: tc, breakLine: true } }, { text: sub, options: { fontSize: 9, color: sc2 } }],
    he({ x: X(x), y: Y(y), w: W(104), h: W(60), align: 'center', valign: 'middle', margin: 2 }));
  if (num) {
    s.addShape(pres.shapes.OVAL, { x: X(x + 94), y: Y(y - 10), w: W(20), h: W(20), fill: { color: C.accent }, line: { color: C.white, width: 1 } });
    s.addText(String(num), { x: X(x + 94), y: Y(y - 10), w: W(20), h: W(20), fontSize: 9, bold: true, color: C.white, fontFace: F, align: 'center', valign: 'middle', margin: 0, isTextBox: true });
  }
}
box(928,25,'רישום המסמך','סטטוס: בעבודה','start',1);
box(808,25,'הגשה לאישור','הוגש לאישור','',2);
box(928,135,'מרשם מסמכים','רשומת המסמך','store');
box(568,135,'מטריצת מאשרים','לפי סוג מסמך','store');
box(88,135,'יומן ביקורת','אושר / נדחה','store',8);
box(688,245,'זיהוי ההגשה','בדיקה כל דקה','',3);
box(568,245,'איתור הכלל','מי מאשר','',4);
box(448,245,'חזרה לעבודה','סטטוס: בעבודה','no');
box(208,245,'נעילת המסמך','מאושר - קריאה בלבד','',7);
box(448,355,'אישור שלב 1','כולם חייבים לאשר','',5);
box(328,465,'אישור סופי','הראשון שמגיב','',6);
s.addNotes('1 רישום, 2 הגשה, 3 הטריגר מזהה, 4 קריאת המטריצה, 5 מאשרי חובה, 6 מאשר סופי, 7 נעילה, 8 יומן ביקורת. דחייה בכל שלב מחזירה לבעבודה ונרשמת ביומן.');

// ---------- slide 5: key facts
s = pres.addSlide(); s.background = { color: 'F5F7F8' };
s.addText('עקרונות', he({ x: 0.6, y: 0.5, w: 12.1, h: 0.8, fontSize: 36, bold: true, color: C.ink, align: 'right', margin: 0 }));
const facts = [
  ['מי מאשר', 'מטריצת המאשרים קובעת לכל סוג מסמך את מאשרי החובה ואת המאשר הסופי. שינוי שם במטריצה חל מההגשה הבאה, בלי לגעת בתהליך.'],
  ['איך מאשרים', 'בפיילוט: במסך האישורים בדף ה-DMS (אישור, דחייה עם הערה, האצלה). בייצור: ב-Teams ובמייל. דחייה אחת מחזירה את המסמך לבעלים.'],
  ['מה נשמר', 'כל החלטה נרשמת ביומן הביקורת ובהחלטות מאשרים, עם זמן, מבצע והערה. הקובץ עצמו נשאר בשרת הקבצים ואינו עובר דרך Power Automate.']];
facts.forEach(([t, b], i) => {
  const x = 8.75 - i * 4.1;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.8, w: 3.8, h: 4.4, rectRadius: 0.1, fill: { color: C.white }, line: { color: C.line, width: 1 }, shadow: { type: 'outer', color: '000000', opacity: 0.12, blur: 6, offset: 2, angle: 90 } });
  s.addShape(pres.shapes.OVAL, { x: x + 2.9, y: 2.1, w: 0.6, h: 0.6, fill: { color: C.accent }, line: { color: C.accent } });
  s.addText(String(i + 1), { x: x + 2.9, y: 2.1, w: 0.6, h: 0.6, fontSize: 18, bold: true, color: C.white, fontFace: F, align: 'center', valign: 'middle', margin: 0, isTextBox: true });
  s.addText(t, he({ x: x + 0.3, y: 2.9, w: 3.2, h: 0.6, fontSize: 22, bold: true, color: C.ink, align: 'right', margin: 0 }));
  s.addText(b, he({ x: x + 0.3, y: 3.6, w: 3.2, h: 2.4, fontSize: 15, color: C.muted, align: 'right', valign: 'top', margin: 0 }));
});
eval(require('fs').readFileSync(__dirname + '/training.js', 'utf8'));
pres.writeFile({ fileName: process.env.OUT || require('path').join(__dirname, '..', 'DMS-Approval-Flow.pptx') }).then(f => console.log('wrote', f));
