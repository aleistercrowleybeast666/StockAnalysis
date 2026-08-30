import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "C:\\Users\\chdxm\\Downloads\\股票分析表_20260830_130121.xlsx";
const outputDir = "D:\\python_software\\StockAnalysis\\artifacts\\v3_audit_tool\\baseline_render";

await fs.mkdir(outputDir, { recursive: true });
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));

const sheets = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  summary: "baseline workbook sheet inventory",
});
await fs.writeFile(path.join(outputDir, "sheets.ndjson"), sheets.ndjson, "utf8");

for (const sheetName of ["A股", "港股", "数据来源说明"]) {
  const table = await workbook.inspect({
    kind: "table",
    range: `'${sheetName}'!A1:AZ12`,
    include: "values,formulas",
    tableMaxRows: 12,
    tableMaxCols: 52,
    summary: `${sheetName} baseline headers and sample rows`,
  });
  await fs.writeFile(path.join(outputDir, `${sheetName}_sample.ndjson`), table.ndjson, "utf8");
  const preview = await workbook.render({
    sheetName,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  await fs.writeFile(path.join(outputDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}

console.log(sheets.ndjson);
