import { CheckCircle2, Circle, MinusCircle, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { STAGE_NAMES, type StageName, type StageState } from "@/lib/schemas";

const LABELS: Record<StageName, string> = {
  profiling: "Profiling",
  cleaning: "Cleaning",
  statistics: "Statistics",
  correlations: "Correlations",
  outliers: "Outliers",
  regression: "Regression",
  visualizations: "Charts",
};

const STATE_TEXT: Record<StageState, string> = {
  pending: "Pending",
  completed: "Done",
  failed: "Failed",
  skipped: "Not run",
};

const ICONS = { pending: Circle, completed: CheckCircle2, failed: XCircle, skipped: MinusCircle } as const;
const TONES: Record<StageState, string> = {
  pending: "text-muted-foreground",
  completed: "text-emerald-700 dark:text-emerald-400",
  failed: "text-destructive",
  skipped: "text-muted-foreground",
};

/** Shows the stage states exactly as the server reports them - no simulated progress. */
export function StageStrip({ stages }: { stages: Partial<Record<StageName, StageState>> }) {
  return (
    <ol aria-label="Analysis stages" className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
      {STAGE_NAMES.map((name) => {
        const state = stages[name] ?? "pending";
        const Icon = ICONS[state];
        return (
          <li key={name} data-stage={name} data-state={state} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2">
            <Icon className={cn("h-4 w-4 shrink-0", TONES[state])} aria-hidden />
            <span className="min-w-0 text-xs">
              <span className="block truncate font-medium">{LABELS[name]}</span>
              <span className={cn("block", TONES[state])}>{STATE_TEXT[state]}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
