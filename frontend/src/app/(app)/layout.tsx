import { Suspense } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { LoadingBlock } from "@/components/ui/state";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  // usePathname() is runtime data for dynamic routes (e.g. /projects/[id]),
  // so the shell must sit behind a Suspense boundary under Cache Components.
  return (
    <Suspense fallback={<LoadingBlock label="Loading" />}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
