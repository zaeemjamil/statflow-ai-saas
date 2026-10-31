"use client";

import { useRef, useState } from "react";
import { Loader2, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useUploadFile } from "@/lib/projects";
import { checkUploadFile, describeUploadLimits } from "@/lib/upload-limits";
import { cn } from "@/lib/utils";

const ACCEPT = ".csv,.xlsx";

export function UploadDropzone({ projectId }: { projectId: string }) {
  const upload = useUploadFile(projectId);
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  // The server is authoritative (type, size, rows, columns, encoding,
  // parseability); this only gives instant feedback for files it is certain
  // to refuse (wrong extension, empty, over the size limit) without
  // uploading them first.
  function submit(file: File | undefined) {
    setLocalError(null);
    if (!file) return;
    const problem = checkUploadFile(file);
    if (problem) {
      setLocalError(problem);
      return;
    }
    upload.mutate(file);
  }

  const error = localError ?? upload.error?.message ?? null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upload your data</CardTitle>
        <CardDescription>
          CSV or Excel (.xlsx). One file per project. {describeUploadLimits()}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            submit(e.dataTransfer.files[0]);
          }}
          className={cn(
            "flex flex-col items-center gap-3 rounded-lg border-2 border-dashed border-border p-10 text-center transition-colors",
            dragging && "border-primary bg-primary/5",
          )}
        >
          {upload.isPending ? (
            <>
              <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden />
              <p role="status" className="text-sm">
                Uploading and profiling your file…
              </p>
            </>
          ) : (
            <>
              <UploadCloud className="h-8 w-8 text-muted-foreground" aria-hidden />
              <p className="text-sm text-muted-foreground">Drag a file here, or</p>
              <Button type="button" variant="outline" onClick={() => inputRef.current?.click()}>
                Choose file
              </Button>
            </>
          )}
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            className="sr-only"
            aria-label="Choose a CSV or Excel file"
            data-testid="file-input"
            disabled={upload.isPending}
            onChange={(e) => {
              submit(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </div>
        {error ? (
          <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
