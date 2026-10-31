import { describe, expect, it } from "vitest";
import {
  MAX_COLUMNS,
  MAX_CSV_MB,
  MAX_ROWS,
  MAX_XLSX_MB,
  SUPPORTED_FORMATS_MESSAGE,
  checkUploadFile,
  describeUploadLimits,
} from "./upload-limits";

const MB = 1024 * 1024;

describe("upload limit defaults", () => {
  it("match the backend V1 defaults", () => {
    expect(MAX_CSV_MB).toBe(25);
    expect(MAX_XLSX_MB).toBe(10);
    expect(MAX_ROWS).toBe(100_000);
    expect(MAX_COLUMNS).toBe(100);
  });

  it("are described to the user", () => {
    expect(describeUploadLimits()).toBe(
      "CSV up to 25 MB, Excel (.xlsx) up to 10 MB; at most 100,000 rows and 100 columns.",
    );
  });
});

describe("checkUploadFile", () => {
  it("accepts csv and xlsx files within their limits", () => {
    expect(checkUploadFile({ name: "a.csv", size: 1 })).toBeNull();
    expect(checkUploadFile({ name: "a.xlsx", size: 1 })).toBeNull();
    expect(checkUploadFile({ name: "A.CSV", size: 1 })).toBeNull();
  });

  it("accepts a file of exactly the limit and refuses one byte more (CSV)", () => {
    expect(checkUploadFile({ name: "a.csv", size: 25 * MB })).toBeNull();
    expect(checkUploadFile({ name: "a.csv", size: 25 * MB + 1 })).toMatch(/over the 25 MB limit for CSV files/);
  });

  it("accepts a file of exactly the limit and refuses one byte more (XLSX)", () => {
    expect(checkUploadFile({ name: "a.xlsx", size: 10 * MB })).toBeNull();
    expect(checkUploadFile({ name: "a.xlsx", size: 10 * MB + 1 })).toMatch(/over the 10 MB limit for Excel \(\.xlsx\) files/);
  });

  it("applies the lower limit to xlsx but not to csv", () => {
    const size = 11 * MB;
    expect(checkUploadFile({ name: "a.csv", size })).toBeNull();
    expect(checkUploadFile({ name: "a.xlsx", size })).not.toBeNull();
  });

  it("states the actual size in the message", () => {
    expect(checkUploadFile({ name: "a.csv", size: 30 * MB })).toContain("30.0 MB");
  });

  it("refuses unsupported extensions", () => {
    for (const name of ["a.xls", "a.txt", "a.json", "a.parquet", "datafile", "a.csv.exe"]) {
      expect(checkUploadFile({ name, size: 1 })).toBe(SUPPORTED_FORMATS_MESSAGE);
    }
  });

  it("refuses an empty file", () => {
    expect(checkUploadFile({ name: "a.csv", size: 0 })).toBe("This file is empty.");
  });
});
