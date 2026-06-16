// Genera PROPUESTA.docx desde PROPUESTA.md
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  PageOrientation, LevelFormat, BorderStyle, ShadingType, WidthType,
  Table, TableRow, TableCell, Header, Footer, PageNumber, PageBreak,
  TabStopType, TabStopPosition
} = require('docx');

const md = fs.readFileSync('PROPUESTA.md', 'utf8');

// --- Parser MD muy simple, ajustado a este documento concreto ---

// Sustituye **bold** y `code` por runs con formato.
function parseInline(text) {
  const runs = [];
  // Tokenizar por **...**, `...`, o texto plano
  const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) {
      runs.push(new TextRun({ text: text.substring(last, m.index), font: 'Calibri' }));
    }
    const tok = m[0];
    if (tok.startsWith('**')) {
      runs.push(new TextRun({ text: tok.slice(2, -2), bold: true, font: 'Calibri' }));
    } else if (tok.startsWith('`')) {
      runs.push(new TextRun({ text: tok.slice(1, -1), font: 'Consolas', size: 20 }));
    }
    last = regex.lastIndex;
  }
  if (last < text.length) {
    runs.push(new TextRun({ text: text.substring(last), font: 'Calibri' }));
  }
  return runs.length ? runs : [new TextRun({ text: '', font: 'Calibri' })];
}

function paragraph(text, opts = {}) {
  return new Paragraph({
    children: parseInline(text),
    spacing: { before: 80, after: 80 },
    ...opts
  });
}

function bulletPara(text) {
  return new Paragraph({
    numbering: { reference: 'bullets', level: 0 },
    children: parseInline(text),
    spacing: { before: 40, after: 40 }
  });
}

function heading(text, level) {
  const sizeMap = { 1: 36, 2: 28, 3: 22 };
  const colorMap = { 1: '0F1117', 2: '00734D', 3: '232735' };
  return new Paragraph({
    heading: level === 1 ? HeadingLevel.HEADING_1 : level === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3,
    children: [new TextRun({ text, bold: true, font: 'Calibri', size: sizeMap[level], color: colorMap[level] })],
    spacing: { before: level === 1 ? 360 : level === 2 ? 280 : 200, after: level === 3 ? 120 : 160 },
    border: level === 2 ? {
      bottom: { color: '00734D', size: 8, space: 4, style: BorderStyle.SINGLE }
    } : undefined
  });
}

function codeBlock(text) {
  const lines = text.split('\n');
  return lines.map((line) =>
    new Paragraph({
      children: [new TextRun({ text: line || ' ', font: 'Consolas', size: 18, color: '232735' })],
      spacing: { before: 0, after: 0, line: 240 },
      shading: { fill: 'F2F3F5', type: ShadingType.CLEAR, color: 'auto' },
      indent: { left: 200 }
    })
  );
}

// --- Parse the markdown into a flat array of children ---

const children = [];
const lines = md.split('\n');
let i = 0;

// Title (first line)
// Skip frontmatter title since we'll render it nicer below

// Cover-like first heading
let coverTitle = '';
let coverSub = '';
while (i < lines.length) {
  const line = lines[i];
  if (line.startsWith('# ')) { coverTitle = line.substring(2).trim(); i++; continue; }
  if (line.startsWith('**') && coverTitle && !coverSub) {
    coverSub = line.replace(/\*\*/g, '').trim();
    i++; continue;
  }
  if (line.trim() === '---') { i++; break; }
  if (line.trim() === '' && coverTitle) { i++; continue; }
  i++;
}

// Cover page
children.push(
  new Paragraph({
    children: [new TextRun({ text: 'PROPUESTA TÉCNICA', font: 'Calibri', size: 24, color: '00734D', bold: true })],
    alignment: AlignmentType.CENTER,
    spacing: { before: 2400, after: 200 }
  }),
  new Paragraph({
    children: [new TextRun({ text: coverTitle || 'Sistema WMS Rollos', font: 'Calibri', size: 56, bold: true, color: '0F1117' })],
    alignment: AlignmentType.CENTER,
    spacing: { before: 100, after: 400 }
  }),
  new Paragraph({
    children: [new TextRun({ text: coverSub || 'TEXCORP S.A.C.', font: 'Calibri', size: 28, color: '232735' })],
    alignment: AlignmentType.CENTER,
    spacing: { before: 100, after: 200 }
  }),
  new Paragraph({
    children: [new TextRun({ text: 'Automatización de movimientos de almacén de telas', font: 'Calibri', size: 22, italics: true, color: '5A6075' })],
    alignment: AlignmentType.CENTER,
    spacing: { before: 100, after: 600 }
  }),
  new Paragraph({ children: [new PageBreak()] })
);

// --- Walk the rest of the markdown ---
function flushParagraphBuffer(buf) {
  if (buf.length) {
    children.push(paragraph(buf.join(' ')));
  }
}

let paraBuf = [];

while (i < lines.length) {
  const line = lines[i];
  const trimmed = line.trim();

  // Skip horizontal rules
  if (trimmed === '---') { flushParagraphBuffer(paraBuf); paraBuf = []; i++; continue; }

  // Code blocks
  if (trimmed.startsWith('```')) {
    flushParagraphBuffer(paraBuf); paraBuf = [];
    const codeLines = [];
    i++;
    while (i < lines.length && !lines[i].trim().startsWith('```')) {
      codeLines.push(lines[i]);
      i++;
    }
    i++; // skip closing ```
    codeBlock(codeLines.join('\n')).forEach((p) => children.push(p));
    continue;
  }

  // Headings
  if (trimmed.startsWith('### ')) {
    flushParagraphBuffer(paraBuf); paraBuf = [];
    children.push(heading(trimmed.substring(4), 3));
    i++; continue;
  }
  if (trimmed.startsWith('## ')) {
    flushParagraphBuffer(paraBuf); paraBuf = [];
    children.push(heading(trimmed.substring(3), 2));
    i++; continue;
  }
  if (trimmed.startsWith('# ')) {
    flushParagraphBuffer(paraBuf); paraBuf = [];
    children.push(heading(trimmed.substring(2), 1));
    i++; continue;
  }

  // Bullet list
  if (trimmed.startsWith('- ')) {
    flushParagraphBuffer(paraBuf); paraBuf = [];
    children.push(bulletPara(trimmed.substring(2)));
    i++; continue;
  }

  // Empty line → flush paragraph
  if (trimmed === '') {
    flushParagraphBuffer(paraBuf); paraBuf = [];
    i++; continue;
  }

  // Plain paragraph line → accumulate
  paraBuf.push(trimmed);
  i++;
}
flushParagraphBuffer(paraBuf);

// --- Build document ---

const doc = new Document({
  creator: 'WMS Rollos',
  title: coverTitle || 'Propuesta WMS Rollos',
  description: 'Propuesta técnica TEXCORP',
  styles: {
    default: {
      document: { run: { font: 'Calibri', size: 22 } }
    },
    paragraphStyles: [
      {
        id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 36, bold: true, font: 'Calibri', color: '0F1117' },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0 }
      },
      {
        id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 28, bold: true, font: 'Calibri', color: '00734D' },
        paragraph: { spacing: { before: 280, after: 160 }, outlineLevel: 1 }
      },
      {
        id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 22, bold: true, font: 'Calibri', color: '232735' },
        paragraph: { spacing: { before: 200, after: 120 }, outlineLevel: 2 }
      }
    ]
  },
  numbering: {
    config: [
      {
        reference: 'bullets',
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      },
      {
        reference: 'numbers',
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } }
        }]
      }
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 }, // US Letter
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    headers: {
      default: new Header({
        children: [new Paragraph({
          alignment: AlignmentType.LEFT,
          children: [
            new TextRun({ text: 'WMS Rollos — Propuesta', font: 'Calibri', size: 18, color: '8B91A3' }),
            new TextRun({ text: '\tTEXCORP S.A.C.', font: 'Calibri', size: 18, color: '8B91A3' })
          ],
          tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
          border: { bottom: { color: 'CCCCCC', size: 4, space: 1, style: BorderStyle.SINGLE } }
        })]
      })
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: 'Página ', font: 'Calibri', size: 18, color: '8B91A3' }),
            new TextRun({ children: [PageNumber.CURRENT], font: 'Calibri', size: 18, color: '8B91A3' }),
            new TextRun({ text: ' de ', font: 'Calibri', size: 18, color: '8B91A3' }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], font: 'Calibri', size: 18, color: '8B91A3' })
          ]
        })]
      })
    },
    children: children
  }]
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync('PROPUESTA.docx', buf);
  console.log('✓ PROPUESTA.docx generado (' + Math.round(buf.length / 1024) + ' KB)');
});
