import { ApiError } from "@/lib/api";

// Only codes whose backend wording is unhelpful in the UI are overridden. Regression
// validation messages (target not numeric / not found / in predictors, ...) are already
// specific and readable, so those pass through unchanged.
const FRIENDLY: Record<string, string> = {
  no_file_uploaded: "Upload a dataset to this project before cleaning or analysing it.",
  analysis_not_completed: "Run the analysis first, then try again.",
  analysis_stage_failed: "This step could not be computed for this dataset.",
  file_unavailable: "The uploaded file could not be found on the server. Try uploading it again.",
  empty_dataset: "This dataset has no rows to analyse.",
};

export function describeAnalysisError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404 && error.code === "not_found") {
      return "This project doesn't exist or you don't have access to it.";
    }
    return FRIENDLY[error.code] ?? error.message;
  }
  if (error instanceof Error) {
    // e.g. a response that no longer matches the contract (zod) or a network failure
    return error.name === "ZodError"
      ? "The server returned an unexpected response. Please try again."
      : "Could not reach the server. Check your connection and try again.";
  }
  return "Something went wrong. Please try again.";
}
