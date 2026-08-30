import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath =
  "D:\\python_software\\StockAnalysis\\artifacts\\v3_live_top100_final.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const inspection = await workbook.inspect({
  kind: "table",
  range: "'港股'!A5:B104",
  include: "values",
  tableMaxRows: 100,
  tableMaxCols: 2,
  maxChars: 30000,
  summary: "港股 Top100 代码与名称",
});

console.log(inspection.ndjson);
