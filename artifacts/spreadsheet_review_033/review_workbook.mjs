import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = process.argv[2];
const outputDir = process.argv[3];
if (!inputPath || !outputDir) {
  throw new Error("usage: review_workbook.mjs <input.xlsx> <output-dir>");
}

await fs.mkdir(outputDir, { recursive: true });
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));

const overview = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 12000,
  tableMaxRows: 8,
  tableMaxCols: 10,
  tableMaxCellChars: 100,
});
console.log("OVERVIEW");
console.log(overview.ndjson);

for (const sheetName of ["A股", "港股", "数据来源说明"]) {
  try {
    const region = await workbook.inspect({
      kind: "region",
      sheetId: sheetName,
      range: "A1:AB12",
      maxChars: 10000,
    });
    console.log(`REGION ${sheetName}`);
    console.log(region.ndjson);
    const preview = await workbook.render({
      sheetName,
      range: "A1:AB12",
      scale: 1.5,
      format: "png",
    });
    await fs.writeFile(
      path.join(outputDir, `${sheetName}.png`),
      new Uint8Array(await preview.arrayBuffer()),
    );
  } catch (error) {
    console.log(`SKIP ${sheetName}: ${error.message}`);
  }
}

const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "formula error scan",
});
console.log("FORMULA_ERRORS");
console.log(formulaErrors.ndjson);
