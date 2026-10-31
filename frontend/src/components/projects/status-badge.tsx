import { cn } from "@/lib/utils";
import type { ProjectStatus } from "@/lib/schemas";

const LABELS: Record<ProjectStatus, string> = {
  created: "Awaiting file",
  uploaded: "Uploaded",
  profiled: "Profiled",
  cleaning_pending: "Cleaning pending",
  cleaning_completed: "Cleaned",
  analyzing: "Analyzing",
  completed: "Analysis complete",
  failed: "Failed",
};

const TONES: Record<ProjectStatus, string> = {
  created: "bg-muted text-muted-foreground",
  uploaded: "bg-muted text-foreground",
  profiled: "bg-primary/15 text-primary",
  cleaning_pending: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  cleaning_completed: "bg-primary/15 text-primary",
  analyzing: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  completed: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  failed: "bg-destructive/15 text-destructive",
};

export function StatusBadge({ status }: { status: ProjectStatus }) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", TONES[status])}>
      {LABELS[status]}
    </span>
  );
}
