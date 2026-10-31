import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { jsonResponse, mockApi, renderWithQuery } from "@/test/helpers";
import { UploadDropzone } from "./upload-dropzone";

const UPLOADED = {
  file: {
    id: "f1", project_id: "p1", original_filename: "data.csv", file_type: "csv",
    size_bytes: 10, row_count: 2, column_count: 1, created_at: "2026-10-01T10:00:00Z",
  },
  profile: {
    row_count: 2, column_count: 1, numeric_column_count: 1, categorical_column_count: 0, date_column_count: 0,
    total_missing_values: 0, duplicate_row_count: 0,
    columns: [{ name: "x", classification: "numeric", pandas_dtype: "int64", missing_count: 0, missing_percentage: 0, unique_count: 2, is_unique: true, min_value: 1, max_value: 2 }],
  },
};

describe("UploadDropzone", () => {
  it("rejects a wrong extension locally without calling the API", async () => {
    const api = mockApi({});
    renderWithQuery(<UploadDropzone projectId="p1" />);
    await userEvent.upload(screen.getByTestId("file-input"), new File(["x"], "notes.txt", { type: "text/plain" }), { applyAccept: false });
    expect(await screen.findByRole("alert")).toHaveTextContent("Only .csv and .xlsx files are supported.");
    expect(api).not.toHaveBeenCalled();
  });

  it("posts the file as multipart form data to the project's upload endpoint", async () => {
    const api = mockApi({ "POST /projects/p1/upload": () => jsonResponse(201, UPLOADED) });
    renderWithQuery(<UploadDropzone projectId="p1" />);
    await userEvent.upload(screen.getByTestId("file-input"), new File(["x\n1\n2\n"], "data.csv", { type: "text/csv" }));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(1));
    const init = api.mock.calls[0][1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("refuses an oversized CSV locally, without calling the API", async () => {
    const api = mockApi({});
    renderWithQuery(<UploadDropzone projectId="p1" />);
    const big = new File(["x"], "big.csv", { type: "text/csv" });
    Object.defineProperty(big, "size", { value: 25 * 1024 * 1024 + 1 }); // avoid allocating 25 MB
    await userEvent.upload(screen.getByTestId("file-input"), big);
    expect(await screen.findByRole("alert")).toHaveTextContent(/over the 25 MB limit for CSV files/);
    expect(api).not.toHaveBeenCalled();
  });

  it("applies the lower XLSX limit locally, but still sends a CSV of the same size", async () => {
    const api = mockApi({ "POST /projects/p1/upload": () => jsonResponse(201, UPLOADED) });
    renderWithQuery(<UploadDropzone projectId="p1" />);
    const size = 11 * 1024 * 1024;

    const xlsx = new File(["x"], "book.xlsx");
    Object.defineProperty(xlsx, "size", { value: size });
    await userEvent.upload(screen.getByTestId("file-input"), xlsx);
    expect(await screen.findByRole("alert")).toHaveTextContent(/over the 10 MB limit for Excel/);
    expect(api).not.toHaveBeenCalled();

    const csv = new File(["x"], "data.csv");
    Object.defineProperty(csv, "size", { value: size });
    await userEvent.upload(screen.getByTestId("file-input"), csv);
    await waitFor(() => expect(api).toHaveBeenCalledTimes(1));
  });

  it("refuses an empty file locally", async () => {
    const api = mockApi({});
    renderWithQuery(<UploadDropzone projectId="p1" />);
    await userEvent.upload(screen.getByTestId("file-input"), new File([], "empty.csv"));
    expect(await screen.findByRole("alert")).toHaveTextContent("This file is empty.");
    expect(api).not.toHaveBeenCalled();
  });

  it("shows the upload limits to the user", () => {
    renderWithQuery(<UploadDropzone projectId="p1" />);
    expect(screen.getByText(/CSV up to 25 MB, Excel \(\.xlsx\) up to 10 MB/)).toBeInTheDocument();
  });

  it.each([
    ["too_many_rows", 422, "This file has more than 100,000 data rows."],
    ["too_many_columns", 422, "This file has 120 columns, but the maximum is 100."],
    ["no_data_rows", 422, "This file has column headers but no data rows."],
    ["unsupported_encoding", 422, "This CSV file is not UTF-8 text."],
    ["file_too_large", 413, "This CSV file is larger than the 25 MB limit for CSV files."],
  ])("surfaces the server's %s message verbatim", async (code, status, message) => {
    mockApi({ "POST /projects/p1/upload": () => jsonResponse(status, { error: { code, message } }) });
    renderWithQuery(<UploadDropzone projectId="p1" />);
    await userEvent.upload(screen.getByTestId("file-input"), new File(["a\n1\n"], "d.csv", { type: "text/csv" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("surfaces the server's rejection message", async () => {
    mockApi({
      "POST /projects/p1/upload": () =>
        jsonResponse(422, { error: { code: "unparseable_file", message: "Could not parse this CSV file." } }),
    });
    renderWithQuery(<UploadDropzone projectId="p1" />);
    await userEvent.upload(screen.getByTestId("file-input"), new File(["bad"], "bad.csv", { type: "text/csv" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not parse this CSV file.");
  });
});
