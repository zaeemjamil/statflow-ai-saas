import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProfileView } from "@/components/projects/profile-view";
import { datasetProfileSchema } from "@/lib/schemas";

const column = {
  name: "a",
  classification: "numeric" as const,
  pandas_dtype: "int64",
  missing_count: 0,
  missing_percentage: 0,
  unique_count: 3,
  is_unique: true,
};
const base = {
  row_count: 3,
  column_count: 1,
  numeric_column_count: 1,
  categorical_column_count: 0,
  date_column_count: 0,
  total_missing_values: 0,
  duplicate_row_count: 0,
  columns: [column],
};

describe("ProfileView import notes", () => {
  it("shows each note with its severity", () => {
    const profile = datasetProfileSchema.parse({
      ...base,
      import_notes: [
        { code: "xlsx_extra_sheets", severity: "warning", message: "Only the first sheet was analysed.", columns: [] },
        { code: "na_text_read_as_missing", severity: "info", message: "NA was read as missing in 'a'.", columns: ["a"] },
      ],
    });
    render(<ProfileView profile={profile} />);
    const list = screen.getByRole("region", { name: /things to check in your data \(2\)/i });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Warning: Only the first sheet was analysed.");
    expect(items[0]).toHaveAttribute("data-severity", "warning");
    expect(items[1]).toHaveTextContent("Note: NA was read as missing in 'a'.");
  });

  it("renders nothing extra for a profile stored before Stage 3", () => {
    const profile = datasetProfileSchema.parse(base);
    render(<ProfileView profile={profile} />);
    expect(screen.queryByText(/things to check/i)).not.toBeInTheDocument();
    expect(screen.getByText("Dataset profile")).toBeInTheDocument();
  });

  it("accepts the new per-column fields", () => {
    const parsed = datasetProfileSchema.parse({
      ...base,
      columns: [{ ...column, likely_identifier: true, identifier_reason: "sequential_integers" }],
    });
    expect(parsed.columns[0].likely_identifier).toBe(true);
  });
});
