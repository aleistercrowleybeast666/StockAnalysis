import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath =
  "D:\\python_software\\StockAnalysis\\artifacts\\v3_live_top100_current.xlsx";
const outputDir = "D:\\python_software\\StockAnalysis\\artifacts\\v3_audit_tool\\current_render";

await fs.mkdir(outputDir, { recursive: true });
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));

for (const [name, range] of [
  ["source_sample", "'数据来源'!A1:N45"],
  ["coverage", "'数据来源说明'!A1:O22"],
  ["a_share_sample", "'A股'!A1:AB12"],
  ["hk_sample", "'港股'!A1:AB12"],
]) {
  const inspection = await workbook.inspect({
    kind: "table",
    range,
    include: "values,formulas",
    tableMaxRows: 45,
    tableMaxCols: 28,
    maxChars: 50000,
    summary: `final ${name}`,
  });
  await fs.writeFile(
    path.join(outputDir, `${name}.ndjson`),
    inspection.ndjson,
    "utf8",
  );
}

for (const sheetName of ["A股", "港股", "数据来源说明"]) {
  const preview = await workbook.render({
    sheetName,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(outputDir, `${sheetName}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

console.log(outputDir);
