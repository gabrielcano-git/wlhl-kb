#!/usr/bin/env node
// Regenerate the Excel view from deterministic JSON exports.
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(scriptsDir);
const dbDir = path.join(root, "database");
const episodes = JSON.parse(await fs.readFile(path.join(dbDir, "episodes.json"), "utf8"));
const issues = JSON.parse(await fs.readFile(path.join(dbDir, "processing_issues.json"), "utf8"));
const topics = JSON.parse(await fs.readFile(path.join(dbDir, "topics.json"), "utf8"));
const quotes = JSON.parse(await fs.readFile(path.join(dbDir, "quotes.json"), "utf8"));
const emailIdeas = JSON.parse(await fs.readFile(path.join(dbDir, "email_ideas.json"), "utf8"));
const hooks = JSON.parse(await fs.readFile(path.join(dbDir, "hooks.json"), "utf8"));

const wb = Workbook.create();
const navy = "#183B4E", teal = "#2E7D78", pale = "#EAF4F3", gold = "#D99B3D", ink = "#20313A";

function scalar(value) {
  return Array.isArray(value) ? value.join("\n• ") : value;
}
function excelText(value) {
  return String(value ?? "").replaceAll('"', '""');
}
function hyperlinkFormula(target, label) {
  return `=HYPERLINK("${excelText(target)}","${excelText(label)}")`;
}
function makeSheet(name, headers, rows, widths = {}) {
  const sheet = wb.worksheets.add(name);
  sheet.showGridLines = false;
  const matrix = [headers, ...rows.map(row => headers.map(h => scalar(row[h] ?? "")))];
  const range = sheet.getRangeByIndexes(0, 0, matrix.length, headers.length);
  range.values = matrix;
  range.format = { font: { name: "Aptos", size: 10, color: ink }, verticalAlignment: "top" };
  range.format.wrapText = true;
  const head = sheet.getRangeByIndexes(0, 0, 1, headers.length);
  head.format = { fill: navy, font: { bold: true, color: "#FFFFFF", size: 10 }, verticalAlignment: "center", wrapText: true };
  head.format.rowHeight = 34;
  sheet.freezePanes.freezeRows(1);
  if (rows.length) {
    const table = sheet.tables.add(`A1:${columnName(headers.length)}${rows.length + 1}`, true, `${name.replace(/[^A-Za-z0-9]/g, "")}Table`);
    table.style = "TableStyleMedium2";
    table.showFilterButton = true;
  }
  headers.forEach((h, i) => {
    sheet.getRangeByIndexes(0, i, Math.max(matrix.length, 1), 1).format.columnWidth = widths[h] || 18;
  });
  if (rows.length) sheet.getRangeByIndexes(1, 0, rows.length, headers.length).format.rowHeight = 54;
  return sheet;
}
function columnName(n) {
  let s = "";
  while (n) { n--; s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26); }
  return s;
}

const episodeHeaders = Object.keys(episodes[0]);
const episodeSheet = makeSheet("Episode Database", episodeHeaders, episodes, {
  "Episode ID": 14, "Episode Number": 14, "Episode Title": 34, "Publish Date": 14,
  "YouTube URL": 31, "Transcript Filename": 42, "Relative Transcript Path": 46,
  "Episode Type": 15, "Review Notes": 46, "Detailed Summary": 45, "Short Summary": 34,
});
episodeSheet.freezePanes.freezeColumns(2);
// Episode identifiers/titles open YouTube; transcript references open the exact local file.
for (let i = 0; i < episodes.length; i++) {
  const row = i + 2;
  const e = episodes[i];
  for (const col of ["A", "B", "C", "E"]) {
    const labels = { A: e["Episode ID"], B: e["Episode Number"], C: e["Episode Title"], E: e["YouTube URL"] };
    episodeSheet.getRange(`${col}${row}`).formulas = [[hyperlinkFormula(e["YouTube URL"], labels[col])]];
  }
  const workbookRelativeTranscript = `../../YT Transcripts/${e["Transcript Filename"]}`;
  episodeSheet.getRange(`F${row}`).formulas = [[hyperlinkFormula(workbookRelativeTranscript, e["Transcript Filename"])]];
  episodeSheet.getRange(`G${row}`).formulas = [[hyperlinkFormula(workbookRelativeTranscript, e["Relative Transcript Path"])]];
}
for (const col of ["A", "B", "C", "E", "F", "G"]) {
  episodeSheet.getRange(`${col}2:${col}${episodes.length + 1}`).format.font = { color: "#0563C1", underline: true };
}

makeSheet("Topic Index", ["Topic", "Number of Episodes", "Episode Numbers", "Episode Titles"], topics, {
  "Topic": 26, "Number of Episodes": 18, "Episode Numbers": 32, "Episode Titles": 48,
});
makeSheet("Quotes", ["Quote", "Episode", "Speaker", "Topic"], quotes, { "Quote": 65, "Episode": 14, "Speaker": 18, "Topic": 25 });
makeSheet("Email Ideas", ["Episode", "Topic", "Email Idea", "Suggested Subject", "CTA"], emailIdeas,
  { "Episode": 14, "Topic": 24, "Email Idea": 55, "Suggested Subject": 42, "CTA": 30 });
makeSheet("Short Hooks", ["Episode", "Topic", "Hook", "Exact Quote or Adapted"], hooks,
  { "Episode": 14, "Topic": 24, "Hook": 58, "Exact Quote or Adapted": 24 });

const issueByEpisode = new Map();
for (const item of issues) {
  const list = issueByEpisode.get(item.Episode) || [];
  list.push(`${item["Issue Type"]}: ${item.Details}`);
  issueByEpisode.set(item.Episode, list);
}
const reviewRows = episodes.map(e => ({
  "Episode": e["Episode Number"],
  "Transcript Filename": e["Transcript Filename"],
  "Reason": "Semantic enrichment pending AI processing",
  "Deterministic Issues": (issueByEpisode.get(e["Episode Number"]) || []).join("\n"),
  "Status": "Review Required",
}));
for (const [episode, details] of issueByEpisode.entries()) {
  if (!episodes.some(e => e["Episode Number"] === episode)) reviewRows.push({
    "Episode": episode, "Transcript Filename": "", "Reason": "Deterministic integrity review",
    "Deterministic Issues": details.join("\n"), "Status": "Review Required",
  });
}
const review = makeSheet("Review Queue", ["Episode", "Transcript Filename", "Reason", "Deterministic Issues", "Status"], reviewRows,
  { "Episode": 14, "Transcript Filename": 46, "Reason": 38, "Deterministic Issues": 68, "Status": 20 });
review.getRange(`E2:E${reviewRows.length + 1}`).format.fill = "#FFF0D5";
for (let i = 0; i < reviewRows.length; i++) {
  const row = i + 2;
  const item = reviewRows[i];
  const episode = episodes.find(e => e["Episode Number"] === item["Episode"] && (!item["Transcript Filename"] || e["Transcript Filename"] === item["Transcript Filename"]));
  if (!episode) continue;
  review.getRange(`A${row}`).formulas = [[hyperlinkFormula(episode["YouTube URL"], item["Episode"])]];
  const workbookRelativeTranscript = `../../YT Transcripts/${episode["Transcript Filename"]}`;
  review.getRange(`B${row}`).formulas = [[hyperlinkFormula(workbookRelativeTranscript, episode["Transcript Filename"])]];
}
review.getRange(`A2:B${reviewRows.length + 1}`).format.font = { color: "#0563C1", underline: true };

const dash = wb.worksheets.add("Dashboard");
dash.showGridLines = false;
dash.getRange("A1:H2").merge();
dash.getRange("A1").values = [["WLHL KNOWLEDGE BASE"]];
dash.getRange("A1:H2").format = { fill: navy, font: { name: "Aptos Display", bold: true, size: 22, color: "#FFFFFF" }, verticalAlignment: "center" };
dash.getRange("A4:B4").values = [["Knowledge Base Status", "Value"]];
dash.getRange("A5:B9").values = [
  ["Total episodes", episodes.length],
  ["Complete transcripts", episodes.filter(e => e["Transcript Status"] === "Complete").length],
  ["Review required", reviewRows.length],
  ["Deterministic issues", issues.length],
  ["Semantic enrichment", "Pending — no AI API used"],
];
dash.getRange("A4:B4").format = { fill: teal, font: { bold: true, color: "#FFFFFF" } };
dash.getRange("A5:A9").format = { fill: pale, font: { bold: true, color: ink } };
dash.getRange("B5:B9").format.font = { bold: true, color: ink, size: 12 };
dash.getRange("A4:B9").format.borders = { preset: "outside", style: "thin", color: "#9DB7B4" };
const typeCounts = Object.entries(episodes.reduce((a, e) => { a[e["Episode Type"] || "Unknown"] = (a[e["Episode Type"] || "Unknown"] || 0) + 1; return a; }, {}));
dash.getRange("D4:E4").values = [["Episode Type", "Count"]];
dash.getRangeByIndexes(4, 3, typeCounts.length, 2).values = typeCounts;
dash.getRange("D4:E4").format = { fill: teal, font: { bold: true, color: "#FFFFFF" } };
dash.getRange("G4:H4").values = [["Enrichment Index", "Count"]];
dash.getRange("G5:H7").values = [["Topics", topics.length], ["Quotes", quotes.length], ["Email ideas / hooks", emailIdeas.length + hooks.length]];
dash.getRange("G4:H4").format = { fill: gold, font: { bold: true, color: "#FFFFFF" } };
dash.getRange("A12:H14").merge();
dash.getRange("A12").values = [["Deterministic infrastructure is complete. Topic, summary, quote, advice, emotional-theme, audience, email, and hook fields remain intentionally blank until an approved AI enrichment method is selected."]];
dash.getRange("A12:H14").format = { fill: "#FFF7E8", font: { italic: true, color: ink, size: 11 }, wrapText: true, verticalAlignment: "center", borders: { preset: "outside", style: "thin", color: gold } };
dash.getRange("A:H").format.columnWidth = 18;
dash.getRange("A:A").format.columnWidth = 26;
dash.getRange("G:G").format.columnWidth = 24;
dash.freezePanes.freezeRows(2);

const output = await SpreadsheetFile.exportXlsx(wb);
const finalWorkbook = path.join(dbDir, "WLHL_Episode_Database.xlsx");
const temporaryDir = await fs.mkdtemp(path.join(os.tmpdir(), "wlhl-xlsx-"));
const temporaryWorkbook = path.join(temporaryDir, "WLHL_Episode_Database.xlsx");
await output.save(temporaryWorkbook);
// LibreOffice refreshes HYPERLINK cached display values when available. Excel also
// recalculates these standard formulas when the workbook is opened.
await fs.rm(finalWorkbook, { force: true });
try {
  const run = promisify(execFile);
  const profile = path.join(temporaryDir, "lo-profile");
  await run("soffice", [`-env:UserInstallation=file://${profile}`, "--headless", "--convert-to", "xlsx", "--outdir", dbDir, temporaryWorkbook]);
} catch {
  await fs.copyFile(temporaryWorkbook, finalWorkbook);
}
await fs.rm(temporaryDir, { recursive: true, force: true });

for (const [sheetName, range] of [
  ["Dashboard", "A1:H14"], ["Episode Database", "A1:H10"], ["Topic Index", "A1:D4"],
  ["Quotes", "A1:D4"], ["Email Ideas", "A1:E4"], ["Short Hooks", "A1:D4"], ["Review Queue", "A1:E10"],
]) {
  const preview = await wb.render({ sheetName, range, scale: 1.2, format: "png" });
  await fs.writeFile(path.join(dbDir, `.preview-${sheetName.replace(/ /g, "-")}.png`), new Uint8Array(await preview.arrayBuffer()));
}
const inspect = await wb.inspect({ kind: "table", range: "Dashboard!A1:H14", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 10 });
console.log(inspect.ndjson);
const errors = await wb.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(errors.ndjson);
